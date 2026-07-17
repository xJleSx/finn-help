export type ChartRange = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y" | "3Y" | "ALL";

export interface PricePoint {
  time: string;
  value: number;
}

export interface VolumePoint {
  time: string;
  value: number;
}

export interface PriceSeries {
  data: PricePoint[];
}

export interface VolumeSeries {
  data: VolumePoint[];
}

export interface ChartData {
  price: PricePoint[];
  volume: VolumePoint[];
}
