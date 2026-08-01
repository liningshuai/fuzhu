# 模板图目录

存放供图像识别使用的按钮/图标截图。按任务分子目录管理，例如：

```
templates/
├── common/          通用按钮（确认、关闭、返回等）
│   └── confirm.png
├── mail/            邮件任务
│   ├── mail_icon.png
│   └── claim_all.png
├── zhengwu/         政务任务
└── yiguan/          驿馆任务
```

## 制作要求

1. 必须在与 `config.yaml` 中 `resolution` 一致的分辨率下截图（默认 1920x1080），
   之后不要改模拟器分辨率，否则所有模板要重做。
2. 用 `python main.py shot` 截屏，再用
   `python tools/crop_template.py captures/xxx.png` 框选裁剪。
3. 裁剪时框紧一点，只保留按钮/图标本身，少带背景。
4. 避免裁剪会变化的区域（数字角标、倒计时文字等）。
