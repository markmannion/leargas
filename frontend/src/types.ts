// Mirrors backend/app/schema.py (contracts/answer.schema.json).

export type QuestionType = 'count' | 'area' | 'length' | 'volume' | 'text' | 'other'
export type Unit = 'count' | 'm' | 'm2' | 'm3' | 'ft' | 'ft2' | 'ft3'
export type Status = 'verified' | 'partial' | 'disagreement' | 'cannot_verify'
export type Source = 'geometry_dxf' | 'geometry_ifc' | 'gemma_ft' | 'gemma_base' | 'mock'
export type Engine = 'auto' | 'geometry' | 'gemma_ft' | 'gemma_base'

export type Pt = [number, number]

export type Shape =
  | { kind: 'polygon'; points: Pt[] }
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

export interface Answer {
  path: string
  question: string
  answer: number | string | null
  unit: Unit | null
  type: QuestionType
  status: Status
  confidence: number
  source: Source
  evidence: Evidence[]
  explanation?: string | null
  sources: SourceAnswer[]
  latency_ms?: number | null
}

export interface AskRequest {
  path: string
  question: string
  type?: QuestionType | null
  engine?: Engine
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
  render: 'image' | 'pdf' | 'dxf'
  questions: DatasetQuestion[]
}

export interface Health {
  ok: boolean
  mode: string
  gold_questions_loaded: number
}
