// Mirrors backend/app/schema.py (contracts/answer.schema.json).

export type QuestionType = 'count' | 'area' | 'length' | 'volume' | 'text' | 'other'
export type Unit = 'count' | 'm' | 'm2' | 'm3' | 'ft' | 'ft2' | 'ft3'
export type Status = 'verified' | 'partial' | 'disagreement' | 'cannot_verify'
export type Source = 'geometry_dxf' | 'geometry_ifc' | 'gemma_ft' | 'gemma_base' | 'sheet_reader' | 'mock'
export type AreaMode = 'whole_rooms' | 'intersection'
export type Engine = 'auto' | 'geometry' | 'gemma_ft' | 'gemma_base' | 'sheet'

export type Pt = [number, number]

export interface Region {
  bbox: [number, number, number, number]
  page: 0
}

export type Shape =
  | { kind: 'polygon'; points: Pt[]; holes?: Pt[][] }
  | { kind: 'bbox'; bbox: [number, number, number, number] }
  | { kind: 'point'; point: Pt }

export interface Evidence {
  shape: Shape
  page: number
  label?: string | null
  value?: number | null
  source?: Source | null
}

export interface SourceAnswer {
  source: Source
  answer: number | string | null
  unit?: Unit | null
  confidence: number
}

export interface RoomArea {
  id: string
  label: string
  room_id?: string | null
  level?: string | null
  value: number
  unit: 'm2'
  method: 'printed' | 'geometry' | 'quantity'
  complete: boolean
  evidence_indices: number[]
}

export interface Answer {
  path: string
  question: string
  region?: Region | null
  area_mode?: AreaMode
  answer: number | string | null
  unit: Unit | null
  type: QuestionType
  status: Status
  confidence: number
  source: Source
  evidence: Evidence[]
  room_areas?: RoomArea[]
  slab_areas?: SlabArea[]
  slab_groups?: SlabGroup[]
  openings?: OpeningItem[]
  explanation?: string | null
  sources: SourceAnswer[]
  latency_ms?: number | null
}

export interface AskRequest {
  path: string
  question: string
  type?: QuestionType | null
  engine?: Engine
  room_breakdown?: boolean
  slab_breakdown?: boolean
  region?: Region | null
  area_mode?: AreaMode
}

// One counted door/window. `number` matches the numbered marker on the sheet.
export interface OpeningItem {
  number: number
  id: string
  kind: 'door' | 'window'
  mark?: string | null
  type_mark?: string | null
  type_name?: string | null
  level?: string | null
  location: string[]
  leaves?: number | null
  width_m?: number | null
  duplicates: string[]
  evidence_index?: number | null
}

export interface SpecificationReference {
  path: string
  page: number
  label: string
}

export interface SlabArea {
  id: string
  mark: string | null
  slab_type: string | null
  level: string | null
  value: number
  unit: 'm2'
  method: 'geometry' | 'quantity'
  thickness_mm: number | null
  reinforcement: string | null
  specification_status: 'known' | 'unknown'
  references: SpecificationReference[]
  warnings: string[]
  evidence_indices: number[]
}

export interface SlabGroup {
  thickness_mm: number | null
  reinforcement: string | null
  specification_status: 'known' | 'unknown'
  value: number
  unit: 'm2'
  slab_ids: string[]
  slab_types?: string[]
}

export interface DatasetQuestion {
  question: string
  answer: number | string | null
  unit: Unit | null
  type: QuestionType
}

export interface Drawing {
  path: string
  collection: string
  name: string
  // 'none': nothing to show (an uploaded IFC model); the engines can still answer.
  render: 'image' | 'pdf' | 'dxf' | 'none'
  // Uploads only: the extensions stored for this stem, e.g. ["dxf", "pdf", "png"].
  files?: string[]
  questions: DatasetQuestion[]
}

export interface UploadResult {
  group: string
  drawing: Drawing
}

export interface Health {
  ok: boolean
  mode: string
  gold_questions_loaded: number
  query_templates?: number
  gemma?: boolean
  gemma_status?: {
    status: 'available' | 'unavailable' | 'unconfigured' | 'checking' | 'disabled'
    available: boolean
    models: Record<string, string>
  }
}
