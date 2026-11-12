import { afterEach,beforeEach,describe,expect,it,vi } from "vitest";
import { cleanup,fireEvent,render,screen,waitFor } from "@testing-library/react";
import AudienceWorkspace from "./AudienceWorkspace";
afterEach(()=>cleanup());
const api=vi.hoisted(()=>({getAudienceProfiles:vi.fn(),createAudienceProfile:vi.fn(),updateAudienceProfile:vi.fn(),deleteAudienceProfile:vi.fn(),confirmAudienceFacts:vi.fn()}));
vi.mock("./api",()=>api);
const item={id:"aud-1",store_id:"store-1",name:"附近上班族",segment_type:"core" as const,audience_description:"工作日午间就餐人群",
 consumption_scenarios_json:["工作日午餐"],consumption_periods_json:["11:30-13:30"],purchase_motivations_json:["出餐快"],common_objections_json:["排队久"],
 source_type:"merchant_observation",source_ref:"门店访谈记录",sample_size:12,sampled_at:null,confidence_level:"medium",fact_status:"pending_confirmation",current_version:1};
describe("audience workspace",()=>{
 beforeEach(()=>{vi.clearAllMocks();window.location.hash="#store:audience";api.getAudienceProfiles.mockResolvedValue({items:[],total:0});api.createAudienceProfile.mockResolvedValue(item);api.confirmAudienceFacts.mockResolvedValue({...item,fact_status:"confirmed",current_version:2});});
 it("creates a sourced audience profile with structured segments",async()=>{
  render(<AudienceWorkspace storeId="store-1"/>);
  fireEvent.click(await screen.findByRole("button",{name:"新增客群"}));
  fireEvent.change(await screen.findByLabelText("客群名称 *"),{target:{value:"附近上班族"}});
  fireEvent.change(screen.getByLabelText("消费场景（每行一项）"),{target:{value:"工作日午餐"}});
  fireEvent.change(screen.getByLabelText("样本量"),{target:{value:"12"}});
  fireEvent.click(screen.getByRole("button",{name:"保存客群"}));
  await waitFor(()=>expect(api.createAudienceProfile).toHaveBeenCalledWith("store-1",expect.objectContaining({name:"附近上班族",consumption_scenarios_json:["工作日午餐"],sample_size:12})));
 });
 it("confirms existing audience facts as a separate action",async()=>{
  api.getAudienceProfiles.mockResolvedValue({items:[item],total:1});
  render(<AudienceWorkspace storeId="store-1"/>);
  fireEvent.click(await screen.findByRole("button",{name:"确认事实"}));
  await waitFor(()=>expect(api.confirmAudienceFacts).toHaveBeenCalledWith("store-1",item));
 });
});
