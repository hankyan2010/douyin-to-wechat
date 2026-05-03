"""封面 AI 生图：复用 dishcomposer 的 jimeng (即梦) t2i 接口。

文生图（不传 binary_data_base64），输出 3:4（贴图常用比例）。
"""
import base64
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from volcengine.visual.VisualService import VisualService

load_dotenv()

VOLC_AK = os.getenv("VOLC_AK")
VOLC_SK = os.getenv("VOLC_SK")
REQ_KEY = os.getenv("VOLC_REQ_KEY", "jimeng_t2i_v40")

if not VOLC_AK or not VOLC_SK:
    raise RuntimeError("缺少 VOLC_AK / VOLC_SK")


def _save(data: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if data.get("binary_data_base64"):
        out_path.write_bytes(base64.b64decode(data["binary_data_base64"][0]))
    elif data.get("image_urls"):
        out_path.write_bytes(requests.get(data["image_urls"][0], timeout=60).content)
    else:
        raise RuntimeError(f"返回结构异常: {data}")
    return out_path


def generate_cover(prompt: str, out_path: Path, width: int = 1024, height: int = 1366) -> Path:
    """3:4 比例（贴图封面常用）。"""
    svc = VisualService()
    svc.set_ak(VOLC_AK)
    svc.set_sk(VOLC_SK)

    form = {
        "req_key": REQ_KEY,
        "prompt": prompt,
        "width": width,
        "height": height,
        "seed": -1,
        "return_url": True,
    }

    print(f"[cover] submitting prompt: {prompt[:60]}...")
    submit = svc.cv_sync2async_submit_task(form)
    if submit.get("code") != 10000:
        raise RuntimeError(f"提交失败: {submit}")
    task_id = submit["data"]["task_id"]

    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(3)
        r = svc.cv_sync2async_get_result({
            "req_key": REQ_KEY,
            "task_id": task_id,
            "req_json": json.dumps({"return_url": True}),
        })
        st = (r.get("data") or {}).get("status")
        if st in ("done", "success"):
            return _save(r["data"], out_path)
        if "fail" in str(st).lower():
            raise RuntimeError(f"任务失败: {r}")
    raise TimeoutError("封面生图超时")


if __name__ == "__main__":
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "小红书插画风，明亮治愈的外卖厨房场景"
    out = generate_cover(prompt, Path(__file__).parent.parent / "output" / "test_cover.png")
    print(f"saved: {out}")
