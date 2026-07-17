"""Generate pipeline architecture diagram for FinAdvisor documentation."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

fig, ax = plt.subplots(1, 1, figsize=(10, 7))
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')

# Color palette
C_DATA = '#4A90D9'       # blue — data
C_TECH = '#50B86C'        # green — technical
C_FUND = '#7B68EE'        # purple — fundamental
C_ML = '#E8833A'          # orange — ML
C_GEO = '#E74C3C'         # red — geo
C_SENT = '#F39C12'        # yellow — sentiment
C_FUSE = '#2C3E50'        # dark — fusion
C_OUT = '#1ABC9C'         # teal — output
C_ARROW = '#95A5A6'       # grey — arrows


def box(ax, x, y, w, h, text, color, subtext=''):
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.1",
        facecolor=color, edgecolor='white', linewidth=1.5,
        alpha=0.9
    )
    ax.add_patch(rect)
    ax.text(x + w/2, y + h/2 + 0.05, text,
            ha='center', va='center', fontsize=7.5, fontweight='bold',
            color='white')
    if subtext:
        ax.text(x + w/2, y + h/2 - 0.25, subtext,
                ha='center', va='center', fontsize=5.5,
                color='white', alpha=0.85)


def arrow(ax, x1, y1, x2, y2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=C_ARROW,
                                lw=1.5, connectionstyle='arc3,rad=0'))


# ── Layer 1: Data ──
box(ax, 3.5, 8.2, 3, 1.0, 'DataLoader', C_DATA,
    'prices, divs, metrics, events, macro')

# ── Layer 2: Analyzers (2 rows of 4) ──
analyzers = [
    (0.3, 6.2, 2.2, 0.8, 'Technical', C_TECH, 'RSI, MACD, BB, SMA, ATR'),
    (2.7, 6.2, 2.2, 0.8, 'Fundamental', C_FUND, 'multipliers, bonds, sectors'),
    (5.1, 6.2, 2.2, 0.8, 'ML Ensemble', C_ML, 'XGB+LGB+Cat → Stacking'),
    (7.5, 6.2, 2.2, 0.8, 'Volatility', C_TECH, 'ATR/HV regimes'),
    (0.3, 4.8, 2.2, 0.8, 'MTF', C_TECH, 'D1/W1/MN consensus'),
    (2.7, 4.8, 2.2, 0.8, 'Sentiment', C_SENT, 'LLM + RSS + social'),
    (5.1, 4.8, 2.2, 0.8, 'Geo Risk', C_GEO, 'sanctions, macro stress'),
    (7.5, 4.8, 2.2, 0.8, 'Events', C_SENT, 'corporate, regulatory'),
]
for x, y, w, h, label, color, desc in analyzers:
    box(ax, x, y, w, h, label, color, desc)

# Arrows: DataLoader → analyzers
for x in [1.4, 3.8, 6.2, 8.6]:
    arrow(ax, 5, 8.2, x, 7.0)

# ── Layer 3: Fusion Engine ──
box(ax, 3.2, 2.8, 3.6, 1.0, 'SignalFusionEngine', C_FUSE,
    'weighted sum + macro + trend + events')

# Arrows: analyzers → Fusion
for x in [1.4, 3.8, 6.2, 8.6]:
    arrow(ax, x, 4.8, x, 3.8)
for x in [1.4, 3.8, 6.2, 8.6]:
    arrow(ax, x, 6.2, x, 3.8)

# ── Layer 4: Output ──
box(ax, 1.5, 0.8, 3.0, 0.9, 'BUY / SELL / HOLD', C_OUT,
    'confidence, max_position')
box(ax, 5.5, 0.8, 3.0, 0.9, 'LLM Advice', C_OUT,
    'Groq / Ollama fallback')

arrow(ax, 5, 2.8, 3, 1.7)
arrow(ax, 5, 2.8, 7, 1.7)

# Title
ax.text(5, 9.6, 'FinAdvisor — Pipeline анализа', ha='center', va='center',
        fontsize=14, fontweight='bold', color='#2C3E50')
ax.text(5, 9.2, 'Data Flow: от сырых данных до торгового сигнала', ha='center',
        va='center', fontsize=9, color='#7F8C8D')

out = Path(__file__).parent / 'pipeline_diagram.png'
fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white',
            edgecolor='none')
plt.close(fig)
print(f'Saved: {out}')
