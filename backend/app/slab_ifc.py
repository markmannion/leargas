"""Read exported IFC slab specifications; never infer reinforcement from concrete or names."""
from math import isfinite
import re

import ifcopenshell.util.element as E
import ifcopenshell.util.unit as U

from .schema import SlabArea, SpecificationReference
from .slabs import specification_text


def unit_scale(unit) -> float:
    if unit.is_a("IfcSIUnit"):
        power = {"AREAUNIT": 2, "VOLUMEUNIT": 3}.get(unit.UnitType, 1)
        return U.get_prefix_multiplier(unit.Prefix) ** power
    if unit.is_a("IfcConversionBasedUnit"):
        factor = unit.ConversionFactor
        return float(factor.ValueComponent.wrappedValue) * unit_scale(factor.UnitComponent)
    raise ValueError("Unsupported IFC specification unit")


def _positive(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0:
        return float(value)
    return None


def _property_sets(obj):
    sets = list(getattr(obj, "HasPropertySets", ()) or ())
    sets += [r.RelatingPropertyDefinition for r in getattr(obj, "IsDefinedBy", ())
             if r.is_a("IfcRelDefinesByProperties")]
    return {ps.id(): ps for ps in sets}.values()


def _properties(obj):
    """Own properties only, keeping entities for explicit units and provenance."""

    def walk(properties, prefix):
        for p in properties:
            if p.is_a("IfcComplexProperty"):
                yield from walk(p.HasProperties, f"{prefix}.{p.Name}")
            elif p.is_a("IfcPropertySingleValue"):
                yield prefix, p.Name, p.NominalValue.wrappedValue if p.NominalValue else None, p
            elif p.is_a("IfcPhysicalSimpleQuantity"):
                yield prefix, p.Name, p[3], p

    for ps in _property_sets(obj):
        yield from walk(getattr(ps, "HasProperties", ()) or getattr(ps, "Quantities", ()) or (), ps.Name)


def _thickness(obj, scale):
    candidates, refs = [], []
    for pset, name, value, prop in _properties(obj):
        key = re.sub(r"[^a-z]", "", name.casefold())
        if key not in ("thickness", "nominalthickness", "slabthickness", "totalthickness", "width", "nominalwidth"):
            continue
        # Width is a thickness quantity for slabs, but is ambiguous in arbitrary property sets.
        if key in ("width", "nominalwidth") and not prop.is_a("IfcQuantityLength"):
            continue
        v = _positive(value)
        if v is None:
            continue
        unit = getattr(prop, "Unit", None)
        if unit is not None and getattr(unit, "UnitType", None) != "LENGTHUNIT":
            continue
        try:
            candidates.append(v * (unit_scale(unit) if unit else scale) * 1000)
        except ValueError:
            continue
        refs.append(f"#{prop.id()} {pset}.{name}")
    if candidates:
        return candidates, refs
    material = E.get_material(obj, should_inherit=False)
    if material is not None and material.is_a("IfcMaterialLayerSetUsage"):
        material = material.ForLayerSet
    if material is not None and material.is_a("IfcMaterialLayerSet"):
        layers = material.MaterialLayers or ()
        values = [_positive(layer.LayerThickness) for layer in layers]
        if values and all(v is not None for v in values):
            return [sum(values) * scale * 1000], [f"#{material.id()} IfcMaterialLayerSet.LayerThickness"]
    return [], []


def _reinforcement_properties(obj, scale):
    parts, refs, warnings = [], [], []
    for pset, name, value, prop in _properties(obj):
        context = f"{pset}.{name}"
        if not re.search(r"reinforc|rebar|mesh", context, re.I):
            continue
        text = specification_text(value)
        if _positive(value) and prop.is_a("IfcPropertySingleValue") and prop.NominalValue.is_a() in (
            "IfcLengthMeasure", "IfcPositiveLengthMeasure", "IfcNonNegativeLengthMeasure",
        ):
            unit = getattr(prop, "Unit", None)
            try:
                text = f"{value * (unit_scale(unit) if unit else scale) * 1000:g} mm"
            except ValueError:
                text = None
        # Presence flags, steel mass/ratio and cover do not specify a reinforcement layout.
        if text and not re.search(r"cover|ratio|mass|weight|volume|isreinforced|hasreinforcement", name, re.I):
            parts.append((name, text))
            refs.append(f"#{prop.id()} {context}")
    values = {}
    for name, text in parts:
        key = name.casefold()
        if key in values and values[key].casefold() != text.casefold():
            warnings.append("Conflicting exported reinforcement properties; reinforcement is unknown.")
        values[key] = text
    if warnings:
        return None, refs, warnings
    return "; ".join(f"{name}: {v}" for name, v in sorted(set(parts))) or None, refs, warnings


def _reinforcement_definitions(obj, scale):
    """IfcPreDefinedPropertySet reinforcement cross sections (IFC2x3 and IFC4)."""
    parts, refs = [], []
    for ps in _property_sets(obj):
        if not ps.is_a("IfcReinforcementDefinitionProperties"):
            continue
        for section in ps.ReinforcementSectionDefinitions or ():
            for bar in section.CrossSectionReinforcementDefinitions or ():
                fields = []
                for attr in ("NominalBarDiameter", "EffectiveDepth"):
                    v = _positive(getattr(bar, attr, None))
                    if v:
                        fields.append(f"{attr}={v * scale * 1000:g} mm")
                if _positive(bar.BarCount):
                    fields.append(f"BarCount={bar.BarCount:g}")
                if _positive(bar.TotalCrossSectionArea):
                    fields.append(f"TotalCrossSectionArea={bar.TotalCrossSectionArea * scale ** 2 * 1e6:g} mm²")
                for attr in ("SteelGrade", "BarSurface"):
                    if (v := specification_text(getattr(bar, attr, None))):
                        fields.append(f"{attr}={v}")
                if fields:
                    role = getattr(section, "ReinforcementRole", None)
                    parts.append(f"Section reinforcement{f' role {role}' if role is not None else ''}: {', '.join(fields)}")
                    refs.append(f"#{ps.id()} IfcReinforcementDefinitionProperties / #{bar.id()}")
    return " | ".join(sorted(set(parts))) or None, refs


def _related_reinforcement(slab):
    seen, bars = set(), []

    def visit(obj):
        if obj.id() in seen:
            return
        if obj != slab and obj.is_a("IfcSlab"):
            return  # a connected neighbouring slab's bars do not belong to this slab
        seen.add(obj.id())
        if obj.is_a("IfcReinforcingBar") or obj.is_a("IfcReinforcingMesh"):
            bars.append(obj)
        for child in E.get_parts(obj) + E.get_components(obj):
            visit(child)

    visit(slab)
    # Explicit product assignments and element connections, never proximity or storey membership.
    for rel in getattr(slab, "ReferencedBy", ()):
        if rel.is_a("IfcRelAssignsToProduct"):
            for obj in rel.RelatedObjects:
                visit(obj)
    for rel in getattr(slab, "ConnectedTo", ()):
        obj = rel.RelatedElement
        if obj.is_a("IfcReinforcingElement") or obj.is_a("IfcElementAssembly"):
            visit(obj)
    for rel in getattr(slab, "ConnectedFrom", ()):
        obj = rel.RelatingElement
        if obj.is_a("IfcReinforcingElement") or obj.is_a("IfcElementAssembly"):
            visit(obj)
    for rel in getattr(slab, "HasAssignments", ()):
        if rel.is_a("IfcRelAssignsToGroup"):
            members = [obj for r in getattr(rel.RelatingGroup, "IsGroupedBy", ()) for obj in r.RelatedObjects]
            if [o.id() for o in members if o.is_a("IfcSlab")] == [slab.id()]:
                for obj in members:
                    visit(obj)
    return bars


def _reinforcement_entities(slab, scale):
    parts, refs = [], []
    for obj in _related_reinforcement(slab):
        typ = E.get_type(obj)
        fields = []
        for attr in ("NominalDiameter", "BarLength", "LongitudinalBarNominalDiameter",
                     "TransverseBarNominalDiameter", "LongitudinalBarSpacing", "TransverseBarSpacing"):
            value = getattr(obj, attr, None)
            if value is None and typ:
                value = getattr(typ, attr, None)
            if _positive(value):
                fields.append(f"{attr}={value * scale * 1000:g} mm")
        for attr in ("SteelGrade", "BarSurface"):
            value = specification_text(getattr(obj, attr, None))
            if value is None and typ:
                value = specification_text(getattr(typ, attr, None))
            if value and value not in ("NOTDEFINED", "USERDEFINED"):
                fields.append(f"{attr}={value}")
        props, _, _ = _reinforcement_properties(obj, scale)
        if props:
            fields.append(props)
        if fields:
            role = getattr(obj, "PredefinedType", None) or getattr(typ, "PredefinedType", None)
            if role and role not in ("NOTDEFINED", "USERDEFINED"):
                fields.append(f"PredefinedType={role}")
            parts.append(f"{obj.is_a()}: {', '.join(fields)}")
            refs.append(f"#{obj.id()} {obj.is_a()} {obj.GlobalId}")
    # Counts and identifiers do not split otherwise equal reinforcement specifications.
    return " | ".join(sorted(set(parts))) or None, refs


def slab_area(model, element, item) -> SlabArea:
    typ = E.get_type(element)
    scale = model._scale["LENGTHUNIT"]
    thickness, thickness_refs = _thickness(element, scale)
    if not thickness and typ is not None:
        thickness, thickness_refs = _thickness(typ, scale)
    warnings = []
    mm = round(thickness[0], 6) if thickness else None
    if thickness and max(thickness) - min(thickness) > 1e-4:
        mm = None
        warnings.append("Conflicting exported thickness properties; thickness is unknown.")
    reinforcement, reinforcement_refs, property_warnings = _reinforcement_properties(element, scale)
    definition, definition_refs = _reinforcement_definitions(element, scale)
    if reinforcement is None and not reinforcement_refs and definition is None and typ is not None:
        reinforcement, reinforcement_refs, property_warnings = _reinforcement_properties(typ, scale)
        definition, definition_refs = _reinforcement_definitions(typ, scale)
    if definition:
        reinforcement = " | ".join(v for v in (reinforcement, definition) if v)
        reinforcement_refs += definition_refs
    related, related_refs = _reinforcement_entities(element, scale)
    if related:
        reinforcement = " | ".join(v for v in (reinforcement, related) if v)
        reinforcement_refs += related_refs
    warnings += property_warnings
    if property_warnings:
        reinforcement = None
    if mm is None and not thickness:
        warnings.append("No exported slab thickness property or complete material layer set.")
    if reinforcement is None:
        warnings.append("No exported reinforcement specification or populated reinforcement relationship.")
    predefined = getattr(element, "PredefinedType", None)
    if predefined in (None, "NOTDEFINED", "USERDEFINED") and typ:
        predefined = getattr(typ, "PredefinedType", None)
    slab_type = specification_text(getattr(typ, "Name", None)) or (
        predefined if predefined not in (None, "NOTDEFINED", "USERDEFINED") else None)
    return SlabArea(
        id=item.guid, mark=element.Tag or element.Name, slab_type=slab_type, level=item.storey,
        value=item.value, method="quantity" if item.method == "qto" else "geometry",
        thickness_mm=mm, reinforcement=reinforcement, warnings=warnings,
        references=[SpecificationReference(path=model.path, label=label) for label in
                    [f"{item.guid} area ({item.method})", *thickness_refs, *reinforcement_refs]],
    )
