"use client";

interface Props {
  search: string;
  onSearch: (value: string) => void;
  typeFilter: "all" | "ofz" | "corp";
  onTypeFilter: (value: "all" | "ofz" | "corp") => void;
}

const TABS: { key: "all" | "ofz" | "corp"; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "ofz", label: "ОФЗ" },
  { key: "corp", label: "Корпоративные" },
];

export default function BondToolbar({
  search,
  onSearch,
  typeFilter,
  onTypeFilter,
}: Props) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur-sm md:flex-row md:items-center md:justify-between">
      <input
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        placeholder="Поиск облигаций..."
        className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-white outline-none transition focus:ring-2 focus:ring-amber-400/30"
      />
      <div className="flex gap-2">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onTypeFilter(key)}
            className={`rounded-xl border px-4 py-2 text-sm transition ${
              typeFilter === key
                ? "border-amber-400/40 bg-amber-400/10 text-amber-300"
                : "border-white/10 text-gray-400 hover:text-white"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
