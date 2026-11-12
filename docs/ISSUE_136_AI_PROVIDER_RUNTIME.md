# Issue #136：AI Provider 生产运行说明

本文记录 AI 文本、图片和视觉质检生产链路的运行配置与安全边界。它补充 `AI_PROVIDER_PROMPT_DOMAIN_DESIGN.md` 的早期设计提案；不替代真实模型账号配置和真机效果验收。

## 1. 运行配置

Provider 默认关闭。只有显式配置下列环境变量后，Worker 才会注册并路由到对应 Provider：

- `AI_PROVIDER_ID`、`AI_PROVIDER_DISPLAY_NAME`：Provider 标识。
- `AI_PROVIDER_BASE_URL`：Provider HTTPS API 根地址。
- `AI_PROVIDER_SECRET_REF`：Secret 引用，不填写明文 API Key。示例引用形式为 `env://AI_PROVIDER_API_KEY`；实际 Secret 值由运行环境 Secret Manager 注入。
- `AI_PROVIDER_REGION`、`AI_PROVIDER_TIMEOUT_SECONDS`：区域与单次请求超时。
- `AI_PROVIDER_TEXT_MODELS`、`AI_PROVIDER_IMAGE_MODELS`、`AI_PROVIDER_VISION_MODELS`、`AI_PROVIDER_OCR_MODELS`：Provider 声明支持的模型能力目录。
- `AI_TEXT_MODEL_ID`、`AI_IMAGE_MODEL_ID`、`AI_VISION_MODEL_ID`：各能力当前选择的模型。
- `AI_PROVIDER_CIRCUIT_FAILURE_THRESHOLD`、`AI_PROVIDER_CIRCUIT_RESET_SECONDS`：熔断阈值与恢复探测间隔。

Prompt 使用已发布版本，按环境配置模板键：

- `AI_PROMPT_TEMPLATE_KEY_MARKETING_STRATEGY`
- `AI_PROMPT_TEMPLATE_KEY_COPY_GENERATION`
- `AI_PROMPT_TEMPLATE_KEY_IMAGE_PROMPT`
- `AI_PROMPT_TEMPLATE_KEY_IMAGE_GENERATION`
- `AI_PROMPT_TEMPLATE_KEY_IMAGE_EDIT`
- `AI_PROMPT_TEMPLATE_KEY_VISUAL_QUALITY_CHECK`

图片输出格式由 `AI_IMAGE_OUTPUT_MIME_TYPE` 控制，支持 PNG、JPEG、WebP。图片还必须通过对象存储完整性校验、尺寸校验和 ClamAV 扫描。相关变量的默认值以仓库根目录 `.env.example` 为准。

## 2. 图片生成与编辑链路

1. Worker 读取已确认的需求、策略和业务事实快照。
2. Text Provider 根据已发布的图片提示词 PromptVersion 生成结构化视觉提示词。
3. Image Provider 执行文生图；有合法源素材时调用同一 Provider 的图片编辑能力。系统不在本地合成或伪造模型图片。
4. Worker 验证返回对象 key 属于当前门店，下载对象并校验 SHA-256、MIME、实际尺寸和恶意内容。
5. Vision Provider 根据已发布的视觉质检 PromptVersion 检查图片，输出结构化 findings、严重度和整改建议。
6. Worker 将图片写入 MediaAsset 与 ArtifactVersion，并把三个模型调用的 AIInvocation、PromptVersion 及源素材引用写入产物来源追踪。

图片生成和编辑使用稳定的 Job 操作幂等键。若 Provider 超时且外部副作用未知，错误保持可重试并记录 AIInvocation；Worker 不把超时误报为确定失败，也不通过本地图片生成绕过 Provider。

## 3. 质检与审核门禁

- Vision 返回 high、critical 或未知严重度时，图片质检不通过并阻断后续审核步骤。
- 质检报告写入图片 ArtifactVersion 的 `vision_inspection` 结构，并保留整改建议。
- AI 质检永远不能替代商家审核。AI 生成图片只有在质检通过且报告声明 `human_review_required=true` 后，才允许进入商家图片审核。
- 商家图片审核和营销任务最终确认仍是独立门禁；AI 不自动批准或发布内容。
- 商家要求修改图片时，任务恢复流程会创建新的 `marketing_task.generate_image` Job，并将商家修改说明、当前需求/策略快照及可用源素材传入 Worker。

## 4. AI 调用与对象生命周期

- AIInvocation 记录 Provider、Model、capability、PromptVersion、请求指纹、Job/Attempt、状态、耗时、错误分类和安全响应引用。
- Strategy、Copy、Video Script 和 Image Artifact 的来源引用会关联本次 Job Attempt 中对应的成功 AIInvocation；缺失调用审计时，Worker 拒绝保存产物。
- 图片对象若在 Provider 调用成功后、MediaAsset/ArtifactVersion 持久化前遗留，清理任务只检查已终态的 failed/cancelled/needs_human Job，且必须超过至少一小时宽限期。
- 清理前再次检查 MediaAsset 与 ArtifactVersion 引用；只删除当前门店 `stores/{store_id}/...` 前缀下的未引用对象。删除结果写回 AIInvocation 响应引用；存储删除失败则保留记录，后续周期重试。
- 清理任务每 15 分钟运行一次。正常已登记素材不会因清理任务被删除。

## 5. 视频脚本边界

视频能力仅生成普通结构化文本：主题、口播稿、文字分镜和拍摄建议。不得创建 VideoArtifact，也不得实现视频生成、剪辑、渲染、转码、上传或发布。

## 6. 测试与真机验收边界

CI 使用可替换的确定性测试 Provider 验证契约、路由、Prompt/Schema、限流、超时、熔断、幂等、审计、跨门店隔离、视觉严重度门禁和对象清理。测试 Provider 只用于自动化测试，不代表真实模型调用成功。

真实 Provider 的密钥注入、账号权限、区域可用性、实际图片质量与真实响应行为，统一由真机测试任务验收，不作为 Issue #136 代码关闭条件。
