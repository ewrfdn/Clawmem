# 模型接口供应商 — 开发者 API 文档平台设计文档

> 2026-09-02 | Sakana + Bocchi 🎸

---

## 1. 定位与目标

我们是**模型接口供应商**，对外提供 API 服务。文档平台是三方开发者接入的核心入口，需要做到：

- **准确性**：文档和实际接口不能漂移
- **可维护性**：团队通过 Markdown 维护，无需前端改动就能更新文档
- **可读性**：每个接口页面同时包含业务说明（手写）和参数/响应（自动生成）
- **多语言**：支持中文 + 英文
- **开发者体验**：在线调试、多语言代码示例、一键复制

对标：Stripe（文档体验标杆）、OpenAI / Anthropic（模型接口行业标准）。

---

## 2. 技术栈选择

| 组件 | 选型 | 理由 |
|---|---|---|
| 框架 | **Nuxt3 + Vue3** | 已有前端项目 |
| 文档内容管理 | **@nuxt/content** (MDC) | 支持 Markdown 嵌入 Vue 组件 |
| 接口参考 (Reference) | **@scalar/nuxt** | 从 openapi.yaml 自动生成完整接口文档页 |
| API 规范 | **OpenAPI 3.1** | Design-first，YAML 作为唯一事实源 |
| Go 端代码生成 | **oapi-codegen** | 从 OpenAPI spec 生成接口类型和校验中间件 |
| 多语言 | **@nuxtjs/i18n** | 内容路由 + UI 词条国际化 |
| Spec CI 门禁 | **oasdiff + redocly** | Breaking change 检测 + Spec 校验 |
| 契约测试 | **Schemathesis** | 端到端漂移检测 |
| Spec 设计工具 | **Stoplight Visual Editor** 或 **Apidog** | 多人协作编辑 openapi.yaml |

---

## 3. 仓库目录结构

```
repo-root/
├── openapi.yaml                    # 🟢 唯一事实源（Design-first）
├── openapi/                        # 拆分后的 spec（可选，大 spec 拆文件）
│   ├── paths/
│   │   ├── chat-completions.yaml
│   │   ├── models.yaml
│   │   └── ...
│   └── schemas/
│       ├── Message.yaml
│       └── ...
│
├── backend/                        # Go 后端
│   ├── cmd/
│   ├── internal/
│   │   ├── handler/                # 实现 oapi-codegen 生成的 interface
│   │   └── middleware/
│   │       └── validator.go        # oapi-codegen 请求校验中间件
│   ├── generated/                  # oapi-codegen 自动生成，别手改
│   │   ├── openapi.gen.go
│   │   └── types.gen.go
│   └── go.mod
│
├── frontend/                       # Nuxt3 文档站
│   ├── nuxt.config.ts
│   ├── components/
│   │   └── content/                # Markdown 嵌入用的文档组件
│   │       ├── ApiEndpoint.vue     # 核心：从 spec 渲染接口参数/响应
│   │       ├── ApiParameterTable.vue
│   │       ├── ApiResponseTabs.vue
│   │       └── Alert.vue           # Markdown 里写 ::alert{type="warning"}
│   ├── content/                    # @nuxt/content 扫描目录
│   │   ├── zh/                     # 🇨🇳 中文文档
│   │   │   ├── index.md
│   │   │   ├── 1.getting-started.md
│   │   │   ├── 2.authentication.md
│   │   │   └── api/
│   │   │       ├── 1.chat-completions.md
│   │   │       ├── 2.models.md
│   │   │       └── 3.embeddings.md
│   │   └── en/                     # 🇺🇸 英文文档
│   │       ├── index.md
│   │       ├── 1.getting-started.md
│   │       ├── 2.authentication.md
│   │       └── api/
│   │           ├── 1.chat-completions.md
│   │           ├── 2.models.md
│   │           └── 3.embeddings.md
│   ├── locales/                    # UI 词条
│   │   ├── zh.json
│   │   └── en.json
│   ├── pages/
│   │   ├── docs/
│   │   │   └── [...slug].vue       # 文档 Catch-all 路由
│   │   └── reference/
│   │       └── [...slug].vue       # Scalar API Reference
│   ├── server/
│   │   └── api/
│   │       └── openapi/
│   │           └── spec.ts         # 服务端：解析并提供 openapi.yaml JSON
│   ├── assets/
│   │   └── openapi.json            # 构建时生成的 dereference 后的 spec
│   └── i18n.config.ts
│
├── .github/
│   └── workflows/
│       ├── docs.yml                # 文档构建 + 多语言校验
│       └── api.yml                 # Spec 校验 + breaking change + 契约测试
│
└── README.md
```

---

## 4. 核心架构流程

### 4.1 日常维护流程

```
日常维护工作流：

  新接口 / 改接口
       │
       ▼
  ┌─────────────────────────┐
  │ 1. 修改 openapi.yaml    │  ← Design-first：spec 先行
  │    (唯一事实源)          │
  └────────────┬────────────┘
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
    后端实现  文档更新   CI 校验
       │       │        │
       ▼       ▼        ▼
  oapi-codegen  手写 md   oasdiff
  生成接口代码   写 guide   检测 breaking
  + 请求校验     插入组件   变更
       │       │        │
       └───────┼────────┘
               ▼
          合并 → CI → 自动部署
```

### 4.2 两类文档的职责划分

| | API Reference（自动） | Guides / 概念（手写） |
|---|---|---|
| 内容 | 端点列表、请求参数、响应 schema、错误码、示例 | 快速开始、鉴权流程、流式最佳实践、迁移指南 |
| 来源 | openapi.yaml → Scalar / Vue 组件渲染 | Markdown 手写维护 |
| 更新方式 | 改 YAML 自动生效 | 改 md 文件 |
| 位于 | `/reference/...` | `/docs/...` |
| 路由 | @scalar/nuxt 自动处理 | @nuxt/content 自动处理 |

---

## 5. 前端文档站实现

### 5.1 Nuxt 配置

```ts
// frontend/nuxt.config.ts
export default defineNuxtConfig({
  modules: [
    '@nuxt/content',     // Markdown 驱动的手写文档
    '@scalar/nuxt',      // OpenAPI 驱动的接口参考
    '@nuxtjs/i18n',      // 多语言
  ],

  content: {
    // 扫描 content/zh 和 content/en 下的 md 文件
    highlight: {
      theme: 'github-dark',
      langs: ['bash', 'json', 'python', 'go', 'typescript']
    }
  },

  scalar: {
    spec: { url: '/openapi.json' },
    pathRouting: { basePath: '/reference' },
    hideModels: false,
  },

  i18n: {
    locales: [
      { code: 'zh', iso: 'zh-CN', name: '简体中文' },
      { code: 'en', iso: 'en-US', name: 'English' },
    ],
    defaultLocale: 'zh',
    strategy: 'prefix_except_default',
  },

  // 别名：让前端能访问仓库根目录的 openapi.yaml
  alias: {
    '@api': resolve(__dirname, '../')
  },

  vite: {
    server: {
      fs: { allow: ['..'] }  // Vite 允许访问 frontend/ 之外
    }
  }
})
```

### 5.2 文档 Catch-all 路由

```vue
<!-- frontend/pages/docs/[...slug].vue -->
<script setup lang="ts">
const { locale } = useI18n()
const route = useRoute()

const slugPath = computed(() => {
  const slug = route.params.slug
  return Array.isArray(slug) ? slug.join('/') : slug || ''
})

const contentPath = computed(() => `/${locale.value}/${slugPath.value}`)

const { data: page } = await useAsyncData(
  `docs-${locale.value}-${route.path}`,
  () => queryContent(contentPath.value).findOne()
)
</script>

<template>
  <ContentDocLayout>
    <ContentRenderer v-if="page" :value="page" />
    <NotFound v-else />
  </ContentDocLayout>
</template>
```

### 5.3 API 接口文档组件

```vue
<!-- frontend/components/content/ApiEndpoint.vue -->
<script setup lang="ts">
const { locale } = useI18n()

const props = defineProps<{
  path: string
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
}>()

const methodColors: Record<string, string> = {
  GET: 'bg-green-100 text-green-800',
  POST: 'bg-blue-100 text-blue-800',
  PUT: 'bg-yellow-100 text-yellow-800',
  DELETE: 'bg-red-100 text-red-800',
}

// 从 openapi.json 中获取该端点的 schema
const { data: endpoint } = await useFetch('/api/openapi/endpoint', {
  query: { path: props.path, method: props.method }
})

// 根据语言返回字段描述
function getLocalizedField(field: any): string {
  if (locale.value === 'zh') {
    return field['x-description-zh'] || field.description || ''
  }
  return field.description || ''
}

// 递归解析 schema 为表格行
function flattenSchema(schema: any, prefix = ''): any[] { /* ... */ }
</script>

<template>
  <div class="api-endpoint my-8 border rounded-xl overflow-hidden">
    <!-- 头部 -->
    <div class="flex items-center gap-3 p-4 bg-gray-50 border-b">
      <span class="px-3 py-1 rounded font-mono text-sm font-bold" :class="methodColors[method]">
        {{ method }}
      </span>
      <code class="text-lg font-mono">{{ path }}</code>
    </div>

    <!-- 描述 -->
    <div class="p-4 border-b" v-if="endpoint?.summary">
      <p class="text-gray-700">{{ endpoint.summary }}</p>
    </div>

    <!-- 请求参数表 -->
    <div class="p-4 border-b">
      <h4 class="font-semibold mb-3">{{ $t('api.parameters') }}</h4>
      <ApiParameterTable
        :schema="endpoint?.requestBody?.content?.['application/json']?.schema"
      />
    </div>

    <!-- 响应示例 (Tab) -->
    <div class="p-4">
      <h4 class="font-semibold mb-3">{{ $t('api.responses') }}</h4>
      <ApiResponseTabs :responses="endpoint?.responses || {}" />
    </div>
  </div>
</template>
```

### 5.4 服务端 API 路由（解析 spec）

```ts
// frontend/server/api/openapi/endpoint.ts
import spec from '~/assets/openapi.json' // 构建时 dereference 后的 spec

export default defineEventHandler((event) => {
  const { path, method } = getQuery(event)
  if (!path || !method) {
    throw createError({ statusCode: 400, statusMessage: 'Missing path or method' })
  }

  const operation = (spec as any).paths?.[path as string]?.[(method as string).toLowerCase()]
  if (!operation) {
    throw createError({ statusCode: 404, statusMessage: 'Endpoint not found in spec' })
  }

  return operation
})
```

---

## 6. 文档编写示例

### 6.1 Markdown 文档文件

```markdown
---
title: 文本对话补全 (Chat Completions)
description: 向模型发送对话消息并获取响应
order: 1
---

# 文本对话补全

这是平台最核心的推理接口。支持同步和流式 (SSE) 返回，
兼容 OpenAI Chat Completions API 格式。

::alert{type="info"}
所有模型 ID 可通过 [模型列表](/docs/api/models) 接口获取。
::

## 接入前必读

1. 先完成 [快速开始](/docs/getting-started) 中的鉴权配置
2. 确保你的环境支持 SSE（流式模式下）

## API Reference

<!-- ✨ 这里嵌入自定义 Vue 组件，自动从 openapi.yaml 读取参数和响应 -->
::api-endpoint{path="/v1/chat/completions" method="POST"}
::

## 流式输出最佳实践

下面是一段 Python 推荐写法：

```python
import openai

client = openai.OpenAI(
    base_url="https://api.yourdomain.com/v1",
    api_key="sk-xxx"
)

stream = client.chat.completions.create(
    model="your-model-v1",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)

for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="")
```

::alert{type="warning"}
流式模式下，最后一个 chunk 的 `finish_reason` 为 `stop`，
此时 `delta.content` 为空，表示生成完毕。
::
```

### 6.2 效果说明

上一段 Markdown 渲染后，开发者看到的是：

1. 标题 + 描述 + Info 提示框（MDC 组件）
2. "接入前必读" 业务说明（手写 Markdown）
3. **接口参数表格 + 请求/响应示例**（`::api-endpoint` Vue 组件，自动从 `openapi.yaml` 生成）
4. 流式最佳实践 + Python 代码块 + 警告框（手写 Markdown + MDC 组件）

**同一个页面，手写叙事 + 自动生成参考，零割裂。**

---

## 7. 国际化 (i18n) 方案

### 7.1 内容目录结构

```
content/
├── zh/                    # 中文
│   ├── 1.getting-started.md
│   └── api/
│       └── 1.chat-completions.md
└── en/                    # 英文（独立的 md 文件，可以有不同的文字表达）
    ├── 1.getting-started.md
    └── api/
        └── 1.chat-completions.md
```

### 7.2 URL 路由规则

| 语言 | URL 示例 |
|---|---|
| 中文（默认） | `/docs/getting-started` |
| 英文 | `/en/docs/getting-started` |

使用 `prefix_except_default` 策略，中文是默认语言，无前缀。

### 7.3 接口描述的多语言策略

| 内容类型 | 语言策略 | 理由 |
|---|---|---|
| 参数名 (field name) | **不翻译** | `messages`, `temperature` 保持英文 |
| 参数类型 | **不翻译** | `string`, `integer` 是代码层面通用的 |
| OpenAPI `description` | **统一英文** | spec 是技术事实源，保持纯净 |
| 参数中文说明 | **x-description-zh 扩展** | 在 YAML 中追加，Vue 组件按 locale 动态读取 |
| 业务说明（手写） | **独立 md 文件** | `zh/` 和 `en/` 各自维护，翻译过程独立 |

### 7.4 UI 词条

```json
// frontend/locales/zh.json
{
  "api": {
    "parameters": "请求参数",
    "responses": "响应示例",
    "required": "必填",
    "optional": "可选",
    "copy": "复制",
    "copied": "已复制",
    "tryIt": "在线调试",
    "noDescription": "暂无说明"
  },
  "nav": {
    "docs": "文档",
    "reference": "接口参考",
    "guide": "指南",
    "changelog": "更新日志"
  }
}
```

```json
// frontend/locales/en.json
{
  "api": {
    "parameters": "Parameters",
    "responses": "Response Examples",
    "required": "Required",
    "optional": "Optional",
    "copy": "Copy",
    "copied": "Copied",
    "tryIt": "Try It",
    "noDescription": "No description"
  }
}
```

---

## 8. 防漂移策略（Design-first 兜底验证）

分五层，从最强到最弱：

| 层级 | 工具 | 防什么漂移 | 执行时机 |
|---|---|---|---|
| ① 编译期 | oapi-codegen interface | 端点缺失、handler 未实现 | go build |
| ② 请求校验 | oapi-codegen middleware | 入参类型 / required / enum 错误 | 运行时，请求层 |
| ③ 响应校验 | kin-openapi ResponseValidator | 响应字段与 spec 不一致 | 集成测试 / 测试环境 |
| ④ 契约测试 | Schemathesis | 端到端真实环境漂移（含边界组合） | CI / Staging 环境 |
| ⑤ Spec 门禁 | oasdiff + redocly lint | spec 被乱改 / 非法修改 | CI 每次 PR |

### 8.1 响应校验配置

```go
// backend/internal/middleware/response_validator_test.go
import (
    "github.com/getkin/kin-openapi/openapi3filter"
)

func TestAllEndpointsRespConformSpec(t *testing.T) {
    swagger, _ := openapi3.NewLoader().LoadFromFile("../../openapi.yaml")
    router := openapi3filter.NewRouter().WithSwagger(swagger)
    
    for _, tc := range testCases {
        resp := doRequest(tc.method, tc.path, tc.body)
        
        err := openapi3filter.ValidateResponse(context.Background(), &openapi3filter.ValidateResponseInput{
            ResponseStatus: resp.StatusCode,
            ResponseHeader: resp.Header,
            ResponseBody:   resp.Body,
            Options:        &openapi3filter.Options{IncludeResponseStatus: true},
        })
        if err != nil {
            t.Errorf("漂移！%s %s 响应不符合 spec: %v", tc.method, tc.path, err)
        }
    }
}
```

### 8.2 Schemathesis CI

```yaml
# .github/workflows/api.yml
jobs:
  contract-test:
    runs-on: ubuntu-latest
    steps:
      - name: Start staging server
        run: docker compose -f docker-compose.staging.yml up -d

      - name: Run Schemathesis
        run: |
          pip install schemathesis
          schemathesis run \
            --stateful=links \
            --checks all \
            --base-url http://localhost:8080 \
            openapi.yaml

  spec-gate:
    runs-on: ubuntu-latest
    steps:
      - name: Breaking change detection
        run: oasdiff breaking openapi.yaml origin/main:openapi.yaml

      - name: Lint spec
        run: npx @redocly/cli lint openapi.yaml --skip-rule no-unused-components
```

---

## 9. 构建时 Spec 处理

`openapi.yaml` 中的 `$ref` 需要在构建时解开（dereference），生成一份打平的 JSON 供前端消费：

```ts
// frontend/scripts/build-openapi.ts
import SwaggerParser from '@apidevtools/swagger-parser'
import fs from 'fs'

async function build() {
  const api = await SwaggerParser.dereference('../openapi.yaml')
  fs.writeFileSync('assets/openapi.json', JSON.stringify(api, null, 2))
  console.log('✅ openapi.json generated')
}

build()
```

```json
// frontend/package.json
{
  "scripts": {
    "build:spec": "npx tsx scripts/build-openapi.ts",
    "dev": "npm run build:spec && nuxt dev",
    "build": "npm run build:spec && nuxt build",
    "docs:validate": "npx @redocly/cli lint ../openapi.yaml"
  }
}
```

---

## 10. CI/CD 完整流水线

```yaml
# .github/workflows/api.yml
name: API & Docs

on:
  pull_request:
    paths:
      - 'openapi.yaml'
      - 'openapi/**'
      - 'frontend/content/**'

jobs:
  spec-validation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint OpenAPI spec
        run: npx @redocly/cli lint openapi.yaml --skip-rule no-unused-components
      - name: Breaking change check
        run: |
          npm install -g oasdiff
          oasdiff breaking openapi.yaml origin/main:openapi.yaml

  docs-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build:spec
      - run: cd frontend && npm run build

  contract-test:
    runs-on: ubuntu-latest
    services:
      staging:
        image: your-registry/staging:latest
        ports: ['8080:8080']
    steps:
      - uses: actions/checkout@v4
      - run: pip install schemathesis && schemathesis run \
          --base-url http://localhost:8080 \
          --checks all openapi.yaml
```

---

## 11. 日常维护 Cheatsheet

| 场景 | 操作 | 涉及文件 |
|---|---|---|
| 新增接口 | 改 openapi.yaml → Go 代码生成 → 实现 handler → 手写 md | `openapi.yaml`, `frontend/content/zh/api/*.md` |
| 修改参数 | 改 openapi.yaml → Go 代码重新生成 → 重新实现 → 改 md 说明 | `openapi.yaml` |
| 修改返回值 | 改 openapi.yaml → 改 Go handler | `openapi.yaml` |
| 新增业务说明 | 手写 md，插入 `::api-endpoint` 组件 | `frontend/content/zh/api/*.md` |
| 新增语言 | `content/` 下加 `fr/` 目录，翻译 md 文件，加 locale 配置 | `frontend/content/fr/`, `frontend/locales/fr.json` |
| 修改文档样式 | 改 Vue 组件 | `frontend/components/content/*.vue` |
| 发版 changelog | 手写 md | `frontend/content/zh/changelog.md` |

---

## 12. 不做什么（明确排除）

- ❌ **不从代码注解生成全部文档**（design-first 原则）
- ❌ **不手写字段参数表格**（Vue 组件从 spec 自动生成）
- ❌ **不引入 GitBook / Readme.io 等 SaaS**（自有站，维护一个 md 就行）
- ❌ **不在 openapi.yaml 里写全部业务说明**（spec 是技术规范，叙事权交给 md）
- ❌ **不翻译参数名和类型**（只翻译描述性文字）

---

## 13. 未来可扩展

- **在线调试 (Try It)**：Scalar 自带，或集成 Postman-like 组件
- **SDK 自动生成**：从 openapi.yaml 生成 Python/JS/Go SDK（openapi-generator）
- **版本化文档**：`/docs/v2/...` 与 `openapi-v2.yaml` 绑定
- **Changelog 自动生成**：oasdiff 的 `changelog` 子命令直接输出人类可读的接口变更日志
