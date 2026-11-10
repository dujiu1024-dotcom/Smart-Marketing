import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

describe("application shell", () => {
  it("shows the product identity and explicitly labels the engineering scaffold", () => {
    render(<App />);
    expect(screen.getByText("AI 门店运营官")).toBeInTheDocument();
    expect(screen.getByText("工程骨架")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("前端应用运行正常");
  });
});
