"use client";

import { useMemo, useState } from "react";
import { Bond } from "@/features/bonds/types/bond";
import { columns } from "./BondColumns";
import Table from "@/features/market/components/table/Table";
import BondStats from "./BondStats";
import BondToolbar from "./BondToolbar";

interface Props {
  bonds: Bond[];
}

const OFZ_PREFIXES = ["SU", "ОФЗ"];

function isOfz(bond: Bond): boolean {
  const ticker = bond.ticker.toUpperCase();
  const name = bond.name.toUpperCase();
  return OFZ_PREFIXES.some((p) => ticker.startsWith(p) || name.includes(p));
}

export default function BondDashboard({ bonds }: Props) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "ofz" | "corp">("all");

  const filtered = useMemo(() => {
    const value = search.toLowerCase();
    return bonds.filter((bond) => {
      const matchesSearch =
        bond.name.toLowerCase().includes(value) ||
        bond.ticker.toLowerCase().includes(value) ||
        bond.issuer.toLowerCase().includes(value);
      if (!matchesSearch) return false;
      if (typeFilter === "ofz") return isOfz(bond);
      if (typeFilter === "corp") return !isOfz(bond);
      return true;
    });
  }, [search, bonds, typeFilter]);

  return (
    <div className="space-y-8">
      <BondStats bonds={filtered} />
      <BondToolbar search={search} onSearch={setSearch} typeFilter={typeFilter} onTypeFilter={setTypeFilter} />
      <Table data={filtered} columns={columns} getRowLink={(bond) => `/instruments/bonds/${bond.ticker}`} />
    </div>
  );
}
