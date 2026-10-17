/* Pyodide Web Worker：在浏览器线程外加载 Python + numpy/pandas，运行算法核心。
 *
 * 主线程通过 postMessage({id, action, payload}) 调用，
 * 本线程回 postMessage({id, ok, result | error})；
 * 加载阶段另回 postMessage({type: "status"|"ready"|"error", message})。
 */
"use strict";

const PYODIDE_VERSION = "0.28.0";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

// 相对 worker.js 的 Python 源码路径（写入虚拟文件系统 /app/ 下，去掉 py/ 前缀）
const PY_FILES = [
  "py/configs/__init__.py",
  "py/configs/defaults.py",
  "py/simulation/__init__.py",
  "py/simulation/clock.py",
  "py/simulation/engine.py",
  "py/simulation/load_model.py",
  "py/simulation/metering.py",
  "py/simulation/scenario.py",
  "py/simulation/schedule_model.py",
  "py/algorithms/__init__.py",
  "py/algorithms/care.py",
  "py/algorithms/detection.py",
  "py/algorithms/deviation.py",
  "py/algorithms/event_state.py",
  "py/algorithms/history.py",
  "py/algorithms/ml_anomaly.py",
  "py/algorithms/pipeline.py",
  "py/algorithms/recognition.py",
  "py/bridge.py",
];

let pyodide = null;
let ready = false;

function post(msg) {
  self.postMessage(msg);
}

async function init() {
  post({ type: "status", message: "正在加载 Python 运行时 (Pyodide)…" });
  importScripts(`${PYODIDE_BASE}pyodide.js`);

  pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });

  post({ type: "status", message: "正在加载 numpy / pandas（首次约数十秒）…" });
  await pyodide.loadPackage(["numpy", "pandas"]);

  post({ type: "status", message: "正在写入算法代码…" });
  pyodide.FS.mkdirTree("/app");
  for (const rel of PY_FILES) {
    const url = new URL(rel, self.location.href).toString();
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`加载源码 ${rel} 失败：HTTP ${resp.status}`);
    }
    const text = await resp.text();
    const dest = "/app/" + rel.replace(/^py\//, "");
    const dir = dest.slice(0, dest.lastIndexOf("/"));
    pyodide.FS.mkdirTree(dir);
    pyodide.FS.writeFile(dest, text);
  }

  pyodide.runPython("import sys\nsys.path.insert(0, '/app')");
  pyodide.runPython("import bridge");
  ready = true;
  post({ type: "ready" });
}

self.onmessage = async (event) => {
  const { id, action, payload } = event.data || {};
  if (!ready) {
    post({ id, ok: false, error: "Python 运行时尚未就绪，请稍候再试。" });
    return;
  }
  try {
    pyodide.globals.set("_action", action);
    pyodide.globals.set("_payload_json", JSON.stringify(payload ?? {}));
    const json = pyodide.runPython("bridge.handle_json(_action, _payload_json)");
    const result = JSON.parse(json);
    post({ id, ok: true, result });
  } catch (err) {
    post({ id, ok: false, error: String(err && err.message ? err.message : err) });
  }
};

init().catch((err) => {
  post({ type: "error", message: String(err && err.message ? err.message : err) });
});
