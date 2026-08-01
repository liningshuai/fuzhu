# -*- coding: utf-8 -*-
"""TaskKey ↔ 识图 yaml 文件名。"""
from __future__ import annotations

from common.models import TaskKey

# 仅登记已有/规划中的 yaml；不存在的文件由 runner 返回 UNSUPPORTED
VISION_YAML: dict[TaskKey, str] = {
    TaskKey.MAIL: "mail.yaml",
    TaskKey.ZHENGWU: "zhengwu.yaml",
    TaskKey.YIGUAN: "yiguan.yaml",
}
