import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import OfferWorkspace from "./OfferWorkspace";
afterEach(() => cleanup());
const api = vi.hoisted(() => ({ getOffers: vi.fn(), createOffer: vi.fn(), updateOffer: vi.fn(), deleteOffer: vi.fn(), confirmOfferFacts: vi.fn() }));
vi.mock("./api", () => api);
const offer = { id:"offer-1", store_id:"store-1", title:"第二杯半价", offer_type:"discount", terms_json:{discount_percent:50}, eligibility_rules_json:{member_only:false}, starts_at:null, ends_at:null, stacking_policy:"not_stackable", usage_limit:null, status:"draft" as const, fact_status:"pending_confirmation", current_version:1 };
describe("store offer workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks(); window.location.hash = "#store:offers";
    api.getOffers.mockResolvedValue({items:[offer],total:1});
    api.createOffer.mockResolvedValue({...offer,id:"offer-2",title:"买一赠一"});
    api.confirmOfferFacts.mockResolvedValue({...offer,fact_status:"confirmed",current_version:2});
  });
  it("loads offers and creates a structured promotion", async () => {
    render(<OfferWorkspace storeId="store-1" />);
    expect(await screen.findByText("第二杯半价")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"新增活动"}));
    fireEvent.change(screen.getByLabelText("活动名称 *"),{target:{value:"买一赠一"}});
    fireEvent.change(screen.getByLabelText("优惠规则（JSON 对象）"),{target:{value:'{"buy_quantity":1,"gift_quantity":1}'}});
    fireEvent.click(screen.getByRole("button",{name:"保存活动"}));
    await waitFor(() => expect(api.createOffer).toHaveBeenCalledWith("store-1",expect.objectContaining({title:"买一赠一",terms_json:{buy_quantity:1,gift_quantity:1},status:"draft"})));
  });
  it("confirms offer facts separately from saving", async () => {
    render(<OfferWorkspace storeId="store-1" />);
    expect(await screen.findByText("第二杯半价")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"确认事实"}));
    await waitFor(() => expect(api.confirmOfferFacts).toHaveBeenCalledWith("store-1",offer));
  });
});
