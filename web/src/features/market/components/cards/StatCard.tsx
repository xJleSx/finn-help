"use client";

interface Props {
    title: string;
    value: string;
    subtitle?: string;
}

export default function StatCard({ title, value, subtitle }: Props) {
    return (
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 backdrop-blur-sm transition-all hover:shadow-lg">
            <div className="text-sm text-gray-500">{title}</div>
            <div className="mt-3 text-3xl font-bold text-white">{value}</div>
            {subtitle && <div className="mt-2 text-sm text-gray-500">{subtitle}</div>}
        </div>
    );
}
