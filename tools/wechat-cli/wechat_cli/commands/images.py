# -*- coding: utf-8 -*-
"""images 命令 — 列出/解密微信 4.x 聊天图片（V2 .dat）

用法：
    wechat-cli images "群名"                    # 列出该会话缓存的图片文件
    wechat-cli images "群名" --decrypt --out DIR # 解密到 DIR
    wechat-cli images "群名" --decrypt --thumb-only --month 2026-11
    wechat-cli images --key show|scan|set <16字节密钥>
"""
import os

import click

from ..core import datimg
from ..core.messages import resolve_chat_context


@click.command("images")
@click.argument("chat_name", required=False)
@click.option("--decrypt", "do_decrypt", is_flag=True, help="解密并把文件写到 --out 目录")
@click.option("--out", "out_dir", default=None, help="输出目录（默认用配置里的 decoded_image_dir）")
@click.option("--month", default=None, help="限定月份，如 2026-11")
@click.option("--thumb-only", is_flag=True, help="只处理缩略图（_t/_h，一定可解）")
@click.option("--key", "key_action", default=None,
              type=click.Choice(["show", "scan", "set"]), help="图片 AES 密钥：show / scan / set")
@click.option("--key-value", default=None, help="配合 --key set 使用")
@click.pass_context
def images(ctx, chat_name, do_decrypt, out_dir, month, thumb_only, key_action, key_value):
    """列出或解密聊天图片（微信 4.x 的 V2 .dat）

    \b
    解密需要两把密钥：
      AES  —— 账户级 16 字节，只在微信里打开过图片时驻留内存，用 --key scan 抓
      XOR  —— 单字节，自动从同图缩略图推算，不用管
    """
    cfg = ctx.obj.cfg

    if key_action:
        if key_action == "show":
            k = datimg.load_image_key(cfg)
            click.echo(k or "(还没有保存 AES 密钥，跑 --key scan，或 --key set <16字节>)")
        elif key_action == "set":
            if not key_value or len(key_value) != 16:
                raise click.BadParameter("--key-value 需要 16 字节 ASCII 密钥")
            p = datimg.save_image_key(cfg, key_value)
            click.echo("已保存到 %s" % p)
        else:
            click.echo("扫内存找 AES 密钥（需要管理员权限，且先在微信里打开看几张图片）...")
            target = chat_name
            sample = None
            if target:
                rc = resolve_chat_context(target, ctx.obj.msg_db_keys, ctx.obj.cache, ctx.obj.decrypted_dir)
                if rc:
                    root = datimg.attach_dir_for(cfg.get("wechat_base_dir"), rc["username"], month)
                    cand = [p for p, _, _ in datimg.list_dat(root, month, thumbs=False)]
                    sample = cand[-1] if cand else None
            if not sample:
                click.echo("需要先给一个会话名，且该会话有 .dat 图片", err=True)
                return
            block = datimg.cipher_block(sample)
            key = datimg.scan_memory_for_aes_key(block)
            if not key:
                click.echo("没扫到。先在微信里打开看 2-3 张图片，再重跑。", err=True)
                return
            p = datimg.save_image_key(cfg, key)
            click.echo("命中 AES 密钥 %s，已保存到 %s" % (key, p))
        return

    if not chat_name:
        raise click.BadParameter("要么给会话名，要么用 --key")

    rc = resolve_chat_context(chat_name, ctx.obj.msg_db_keys, ctx.obj.cache, ctx.obj.decrypted_dir)
    if not rc:
        click.echo("找不到会话：%s" % chat_name, err=True)
        return

    username = rc["username"]
    root = datimg.attach_dir_for(cfg.get("wechat_base_dir"), username, month)
    items = datimg.list_dat(root, month, thumbs=not thumb_only)
    if not items:
        click.echo("这个会话没有缓存图片（%s）" % root)
        return

    click.echo("%s（%s）共 %d 个 .dat" % (rc["display_name"], username, len(items)))
    if not do_decrypt:
        for p, size, mtime in items:
            import datetime
            ts = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            click.echo("  %s  %7.1f KB  %s" % (os.path.basename(p), size / 1024, ts))
        click.echo("\n加 --decrypt --out <目录> 解密")
        return

    aes_key = datimg.load_image_key(cfg)
    if not aes_key:
        click.echo("还没有 AES 密钥：先 wechat-cli images <会话> --key scan", err=True)
        return
    out_dir = out_dir or cfg.get("decoded_image_dir") or "decoded_images"
    os.makedirs(out_dir, exist_ok=True)

    ok = failed = 0
    for p, _, _ in items:
        thumb = p[:-4] + "_t.dat"
        xor_key = datimg.xor_key_from_thumb(thumb) if os.path.isfile(thumb) else None
        if xor_key is None:
            xor_key = datimg.xor_key_from_thumb(p)
        base = os.path.splitext(os.path.basename(p))[0]
        tmp = os.path.join(out_dir, base + ".raw")
        try:
            datimg.decrypt_v2(p, aes_key, xor_key, tmp)
            with open(tmp, "rb") as f:
                ext = datimg.guess_ext(f.read(8))
            final = os.path.join(out_dir, base + ext)
            os.replace(tmp, final)
            ok += 1
        except Exception as exc:
            failed += 1
            if os.path.exists(tmp):
                os.remove(tmp)
            click.echo("  失败 %s: %s" % (os.path.basename(p), exc), err=True)
    click.echo("解密完成：成功 %d，失败 %d，输出到 %s" % (ok, failed, out_dir))
    if failed:
        click.echo("提示：全尺寸图可能解成 .wxgf 容器（微信表情/动图格式），缩略图才是标准 JPEG", err=True)
