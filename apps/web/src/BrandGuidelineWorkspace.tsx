import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  confirmBrandGuidelineFacts,
  createBrandGuideline,
  getBrandGuideline,
  updateBrandGuideline,
  type BrandGuideline,
  type BrandGuidelineInput,
} from "./api";

interface BrandForm {
  brand_story: string;
  positioning: string;
  differentiators: string;
  core_values: string;
  tone_of_voice: string;
  common_phrases: string;
  prohibited_phrases: string;
  cta_preferences: string;
  logo_asset_id: string;
  color_palette: string;
  font_preferences: string;
  visual_style: string;
}

const emptyForm: BrandForm = {
  brand_story: "",
  positioning: "",
  differentiators: "",
  core_values: "",
  tone_of_voice: "",
  common_phrases: "",
  prohibited_phrases: "",
  cta_preferences: "",
  logo_asset_id: "",
  color_palette: "[]",
  font_preferences: "",
  visual_style: "",
};

function lines(value: string): string[] {
  return value.split(/[\n、,，]/).map((item) => item.trim()).filter(Boolean);
}

function jsonArray(value: string): Array<Record<string, unknown>> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("品牌色彩规范必须是有效 JSON 数组。");
  }
  if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("品牌色彩规范必须是对象数组，例如 [{\"name\":\"主色\",\"hex\":\"#245744\"}]。");
  }
  return parsed as Array<Record<string, unknown>>;
}

function fromGuideline(value: BrandGuideline): BrandForm {
  return {
    brand_story: value.brand_story ?? "",
    positioning: value.positioning ?? "",
    differentiators: value.differentiators ?? "",
    core_values: (value.core_values_json ?? []).join("\n"),
    tone_of_voice: value.tone_of_voice ?? "",
    common_phrases: (value.common_phrases_json ?? []).join("\n"),
    prohibited_phrases: (value.prohibited_phrases_json ?? []).join("\n"),
    cta_preferences: (value.cta_preferences_json ?? []).join("\n"),
    logo_asset_id: value.logo_asset_id ?? "",
    color_palette: JSON.stringify(value.color_palette_json ?? [], null, 2),
    font_preferences: (value.font_preferences_json ?? []).join("\n"),
    visual_style: value.visual_style ?? "",
  };
}

function toGuideline(form: BrandForm): BrandGuidelineInput {
  return {
    brand_story: form.brand_story.trim() || null,
    positioning: form.positioning.trim() || null,
    differentiators: form.differentiators.trim() || null,
    core_values_json: lines(form.core_values),
    tone_of_voice: form.tone_of_voice.trim() || null,
    common_phrases_json: lines(form.common_phrases),
    prohibited_phrases_json: lines(form.prohibited_phrases),
    cta_preferences_json: lines(form.cta_preferences),
    logo_asset_id: form.logo_asset_id.trim() || null,
    color_palette_json: jsonArray(form.color_palette),
    font_preferences_json: lines(form.font_preferences),
    visual_style: form.visual_style.trim() || null,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}

function TextField({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return <label className="field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function TextArea({ label, value, onChange, rows = 3, placeholder }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return <label className="field span-2"><span>{label}</span><textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export default function BrandGuidelineWorkspace({ storeId }: { storeId: string }) {
  const [guideline, setGuideline] = useState<BrandGuideline | null>(null);
  const [form, setForm] = useState<BrandForm>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const value = await getBrandGuideline(storeId);
      setGuideline(value);
      setForm(fromGuideline(value));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) {
        setGuideline(null);
        setForm(emptyForm);
      } else {
        setError(errorMessage(reason));
      }
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => { void reload(); }, [reload]);

  function change<K extends keyof BrandForm>(key: K, value: BrandForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setNotice("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const input = toGuideline(form);
      const saved = guideline
        ? await updateBrandGuideline(storeId, guideline, input)
        : await createBrandGuideline(storeId, input);
      setGuideline(saved);
      setForm(fromGuideline(saved));
      setNotice(`品牌规范已保存为 V${saved.current_version}，状态为待确认。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function confirmFacts() {
    if (!guideline) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const confirmed = await confirmBrandGuidelineFacts(storeId, guideline);
      setGuideline(confirmed);
      setForm(fromGuideline(confirmed));
      setNotice(`品牌规范 V${confirmed.current_version} 已确认。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">BRAND GUIDELINE</p><h1>品牌规范</h1><p className="muted">维护品牌定位、表达边界和视觉规范，让 AI 的内容产出保持品牌一致。</p></div>{guideline && <div className="version-chip">V{guideline.current_version} · {guideline.fact_status === "confirmed" ? "已确认" : "待确认"}</div>}</div>
      {error && <div className="alert error" role="alert">{error}{(error.includes("changed") || error.includes("冲突")) && <button className="text-button" onClick={() => void reload()}>重新加载</button>}</div>}
      {notice && <div className="alert success" role="status">{notice}</div>}
      {loading ? <div className="loading-card"><span className="spinner" />正在读取品牌规范…</div> : (
        <form className="profile-form" onSubmit={save}>
          <section className="form-card"><div className="section-title"><div><h2>品牌定位</h2><p>帮助 AI 理解品牌是谁、服务谁，以及与同类门店的区别。</p></div></div><div className="form-grid">
            <TextArea label="品牌故事" value={form.brand_story} onChange={(v) => change("brand_story", v)} />
            <TextArea label="品牌定位" value={form.positioning} onChange={(v) => change("positioning", v)} />
            <TextArea label="差异化优势" value={form.differentiators} onChange={(v) => change("differentiators", v)} />
            <TextField label="核心价值（每行一项）" value={form.core_values} onChange={(v) => change("core_values", v)} placeholder="品质、专业、友好…" />
          </div></section>
          <section className="form-card"><div className="section-title"><div><h2>语言与表达规范</h2><p>明确品牌语气、常用表达和禁止承诺，降低营销内容风险。</p></div></div><div className="form-grid">
            <TextArea label="品牌语气" value={form.tone_of_voice} onChange={(v) => change("tone_of_voice", v)} rows={2} />
            <TextArea label="常用表达（每行一项）" value={form.common_phrases} onChange={(v) => change("common_phrases", v)} rows={3} />
            <TextArea label="禁用表达 / 禁止承诺（每行一项）" value={form.prohibited_phrases} onChange={(v) => change("prohibited_phrases", v)} rows={3} />
            <TextArea label="行动号召偏好（每行一项）" value={form.cta_preferences} onChange={(v) => change("cta_preferences", v)} rows={2} />
          </div></section>
          <section className="form-card"><div className="section-title"><div><h2>视觉规范</h2><p>保存品牌视觉方向和可复用的设计约束。</p></div></div><div className="form-grid">
            <TextArea label="视觉风格" value={form.visual_style} onChange={(v) => change("visual_style", v)} rows={2} />
            <TextField label="字体偏好（每行一项）" value={form.font_preferences} onChange={(v) => change("font_preferences", v)} placeholder="思源黑体、无衬线…" />
            <TextField label="Logo 素材资产 ID" value={form.logo_asset_id} onChange={(v) => change("logo_asset_id", v)} placeholder="素材库接入后可从资产选择" />
            <TextArea label="品牌色彩（JSON 对象数组）" value={form.color_palette} onChange={(v) => change("color_palette", v)} rows={4} placeholder='[{"name":"主色","hex":"#245744"}]' />
          </div></section>
          <div className="form-footer"><p>{guideline ? `保存会生成新版本；当前 V${guideline.current_version}。` : "首次保存后可核对并确认品牌规范。"}</p><div className="form-actions">{guideline && <button className="secondary" type="button" onClick={() => void reload()}>放弃修改</button>}{guideline && guideline.fact_status !== "confirmed" && <button className="secondary" type="button" disabled={saving} onClick={() => void confirmFacts()}>确认资料</button>}<button className="primary" type="submit" disabled={saving}>{saving ? "保存中…" : guideline ? "保存规范" : "创建品牌规范"}</button></div></div>
        </form>
      )}
    </>
  );
}
