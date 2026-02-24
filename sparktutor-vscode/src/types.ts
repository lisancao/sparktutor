/** Shared TypeScript interfaces matching Python dataclasses. */

export interface CourseMeta {
  id: string;
  title: string;
  description: string;
  lessonCount: number;
  requiresLakehouse: boolean;
  lessons: string[];
}

export interface CourseProgress {
  started: boolean;
  currentLessonId?: string;
  currentLessonIdx?: number;
  lessonsCompleted?: number;
  totalLessons?: number;
  depth?: string;
  updatedAt?: string;
}

export interface StepData {
  cls: string;
  depth: string;
  output: string;
  answerChoices: string | null;
  correctAnswer: string | null;
  hint: string | null;
  starterCode: string | null;
  solutionCode: string | null;
  requiresExecution: boolean;
  lessonTitle: string | null;
  estimatedMinutes: number | null;
  validation: ValidationRule[];
}

export interface ValidationRule {
  type: string;
  params: Record<string, unknown>;
}

export interface FeedbackItem {
  line: number | null;
  severity: "error" | "warning" | "info" | "success";
  message: string;
  suggestion: string | null;
}

export interface EvalResult {
  passed: boolean;
  feedback: FeedbackItem[];
  encouragement: string;
  skillSignals: string[];
}

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  mode: string;
}

export interface LoadLessonResult {
  step: StepData;
  currentIndex: number;
  totalSteps: number;
  lessonTitle: string;
  lessonId: string;
  restoredCode: string;
  starterCode: string;
}

export interface StepResult {
  step: StepData;
  currentIndex: number;
  totalSteps: number;
  starterCode: string;
}

export interface AdvanceResult {
  finished: boolean;
  step?: StepData;
  currentIndex?: number;
  totalSteps?: number;
  starterCode?: string;
}

export interface GoBackResult {
  atStart: boolean;
  step?: StepData;
  currentIndex?: number;
  totalSteps?: number;
  starterCode?: string;
}
