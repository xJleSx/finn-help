"use client";

import { useEffect, useRef } from "react";
import { createChart, AreaSeries, HistogramSeries, ColorType } from "lightweight-charts";
import type { IChartApi, ISeriesApi, AreaSeriesPartialOptions, HistogramSeriesPartialOptions } from "lightweight-charts";
import type { PricePoint, VolumePoint } from "@/types/chart";

interface Props {
  priceData: PricePoint[];
  volumeData: VolumePoint[];
  height?: number;
}

export default function PriceChart({ priceData, volumeData, height = 320 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a1a1aa",
      },
      grid: {
        vertLines: { color: "#27272a" },
        horzLines: { color: "#27272a" },
      },
      rightPriceScale: {
        borderColor: "#27272a",
      },
      timeScale: {
        borderColor: "#27272a",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "#52525b", width: 1, style: 2, labelBackgroundColor: "#18181b" },
        horzLine: { color: "#52525b", width: 1, style: 2, labelBackgroundColor: "#18181b" },
      },
      handleScroll: false,
      handleScale: false,
    });

    const areaOptions: AreaSeriesPartialOptions = {
      lineColor: "#22c55e",
      topColor: "#22c55e40",
      bottomColor: "#22c55e00",
      lineWidth: 2,
    };
    const area = chart.addSeries(AreaSeries, areaOptions);
    area.setData(priceData);
    areaRef.current = area;

    const volOptions: HistogramSeriesPartialOptions = {
      color: "#3f3f46",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    };
    const volume = chart.addSeries(HistogramSeries, volOptions);
    volume.setData(volumeData);
    volumeRef.current = volume;

    chart.timeScale().fitContent();

    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  return <div ref={containerRef} className="w-full" />;
}
