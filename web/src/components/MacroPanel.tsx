"use client";

export default function MacroPanel() {
  return (
    <section className="bg-white/[0.04] border border-white/10 rounded-2xl p-5 backdrop-blur-sm">
      <h3 className="text-sm font-light text-white mb-3">Макро</h3>
      <div className="text-xs text-gray-400 space-y-1.5" id="macro-panel">
        <div className="flex justify-between"><span>Brent</span><span className="font-mono text-white" id="macro-brent">—</span></div>
        <div className="flex justify-between"><span>USD/RUB</span><span className="font-mono text-white" id="macro-usd">—</span></div>
        <div className="flex justify-between"><span>IMOEX</span><span className="font-mono text-white" id="macro-imoex">—</span></div>
        <div className="flex justify-between"><span>Ключевая ставка</span><span className="font-mono text-white" id="macro-rate">—</span></div>
        <div className="flex justify-between"><span>Инфляция</span><span className="font-mono text-white" id="macro-cpi">—</span></div>
      </div>
    </section>
  );
}
