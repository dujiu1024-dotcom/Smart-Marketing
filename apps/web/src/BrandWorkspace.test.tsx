import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import BrandWorkspace from "./BrandWorkspace";
import { ApiError } from "./api";
afterEach(()=>cleanup());
const api=vi.hoisted(()=>({getBrandGuideline:vi.fn(),createBrandGuideline:vi.fn(),updateBrandGuideline:vi.fn(),confirmBrandGuidelineFacts:vi.fn()}));
vi.mock("./api",async()=>{const actual=await vi.importActual<typeof import("./api")>("./api");return {...actual,...api};});
const brand={id:"brand-1",store_id:"store-1",brand_story:"坚持现制",positioning:"社区茶饮",differentiators:"每日鲜萃",core_values_json:["真实"],tone_of_voice:"清爽直接",common_phrases_json:["每日现制"],prohibited_phrases_json:["全网第一"],cta_preferences_json:["到店体验"],logo_asset_id:null,color_palette_json:[{name:"主色",hex:"#245B45"}],font_preferences_json:["思源黑体"],visual_style:"自然简洁",fact_status:"pending_confirmation",current_version:1};
describe("brand guideline workspace",()=>{
 beforeEach(()=>{vi.clearAllMocks();api.getBrandGuideline.mockResolvedValue(brand);api.createBrandGuideline.mockResolvedValue({...brand,current_version:1});api.updateBrandGuideline.mockResolvedValue({...brand,current_version:2});api.confirmBrandGuidelineFacts.mockResolvedValue({...brand,fact_status:"confirmed",current_version:2});});
 it("creates brand guideline from an empty store state",async()=>{
  api.getBrandGuideline.mockRejectedValue(new ApiError("not found",404,"RESOURCE_NOT_FOUND"));
  render(<BrandWorkspace storeId="store-1"/>);
  fireEvent.change(await screen.findByLabelText("品牌定位"),{target:{value:"社区精品茶饮"}});
  fireEvent.click(screen.getByRole("button",{name:"创建品牌规范"}));
  await waitFor(()=>expect(api.createBrandGuideline).toHaveBeenCalledWith("store-1",expect.objectContaining({positioning:"社区精品茶饮",logo_asset_id:null})));
 });
 it("blocks confirmation while edits are unsaved and confirms after save",async()=>{
  render(<BrandWorkspace storeId="store-1"/>);
  expect(await screen.findByDisplayValue("社区茶饮")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("品牌定位"),{target:{value:"社区精品茶饮"}});
  expect(screen.getByRole("button",{name:"确认规范"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"保存品牌规范"}));
  await waitFor(()=>expect(api.updateBrandGuideline).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button",{name:"确认规范"}));
  await waitFor(()=>expect(api.confirmBrandGuidelineFacts).toHaveBeenCalledWith("store-1",expect.objectContaining({current_version:2})));
 });
});
