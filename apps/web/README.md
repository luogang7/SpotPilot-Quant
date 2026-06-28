# SpotPilot Quant Web

Vue 3 + Vite + TypeScript 前端工作台，基于根目录 `spotpilot_quant_local_prd.md` 搭建，为 SpotPilot Quant（现货量化领航台）提供 Dashboard、Market、Strategy、Backtest、AI分析、Trading、Risk、Logs 和 Settings 页面。

## Run

```bash
npm install
npm run dev
```

默认 API 代理到 `http://localhost:8001`，也可以通过 `VITE_API_BASE_URL` 指定完整 API 前缀。

## Architecture

```text
src/app       router + Pinia store
src/layouts   workbench shell
src/shared    API client, typed contracts, base components
src/features  PRD page modules
src/styles    global design tokens
```
