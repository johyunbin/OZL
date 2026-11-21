// 빌드 결과 폴더와 자료 폴더를 정하는 한 곳(astro.config.mjs, guard.mjs, pagefind.mjs, fonts.mjs 가 함께 쓴다).
import path from "node:path";
import { fileURLToPath } from "node:url";

export const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_ROOT = path.resolve(WEB_ROOT, "../..");
export const PUBLIC_DIST = path.join(WEB_ROOT, "dist");
// 사용하는 이름만 둔다. 값의 정본은 src/ozl/paths.py 의 LAYOUT 이다.
const LAYOUT = {
  out: "out",
};

const CHECKOUT_PRIVATE = path.join(REPO_ROOT, "private");
// 표식 없이 비울 수 있는 기존 폴더는 환경 변수로 옮기지 않는다.
export const CHECKOUT_PREVIEW = path.join(CHECKOUT_PRIVATE, LAYOUT.out, "web_preview");

export function privateRoot() {
  return path.resolve(process.env.OZL_PRIVATE?.trim() || CHECKOUT_PRIVATE);
}

export function privateAt(name, ...parts) {
  if (!Object.hasOwn(LAYOUT, name)) throw new Error(`모르는 비공개 경로: ${name}`);
  return path.join(privateRoot(), LAYOUT[name], ...parts);
}

export const PREVIEW_DEFAULT = privateAt("out", "web_preview");
/** 빌드가 결과 폴더에 남기는 표식. guard.mjs 는 이 표식이 있는 폴더만 비운다. */
export const OUT_MARK = ".ozl-web-out";

export function buildMode() {
  return process.env.OZL_BUILD_MODE === "public" ? "public" : "preview";
}

export function outDir(mode = buildMode()) {
  if (process.env.OZL_WEB_OUT) return path.resolve(process.env.OZL_WEB_OUT);
  return mode === "public" ? PUBLIC_DIST : privateAt("out", "web_preview");
}

export function basePath(mode = buildMode()) {
  return mode === "public" ? "/" : "/preview/";
}

export function siteData() {
  return path.resolve(process.env.OZL_SITE_DATA || path.join(WEB_ROOT, "sample-data"));
}
