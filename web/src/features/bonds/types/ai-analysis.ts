export interface AIAnalysis {
  summary: string;
  strengths: string[];
  weaknesses: string[];
  risks: string[];
  recommendation: string;
  investmentHorizon: string;
  confidence: number;
}
