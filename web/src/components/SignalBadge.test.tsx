import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalBadge } from "./SignalBadge";

describe("SignalBadge", () => {
  it("renders buy signal", () => {
    render(<SignalBadge signal={{ fused: "buy", confidence: 0.85 }} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("renders sell signal", () => {
    render(<SignalBadge signal={{ fused: "sell", confidence: 0.72 }} />);
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
  });

  it("renders hold signal without confidence", () => {
    render(<SignalBadge signal={{ fused: "hold" }} />);
    expect(screen.getByText("Hold")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("renders strong_buy signal", () => {
    render(<SignalBadge signal={{ fused: "strong_buy" }} />);
    expect(screen.getByText("Strong Buy")).toBeInTheDocument();
  });

  it("renders hold as fallback for unknown signal", () => {
    const signal = { someOtherField: "value" } as Record<string, unknown>;
    render(<SignalBadge signal={signal} />);
    expect(screen.getByText("Hold")).toBeInTheDocument();
  });
});
