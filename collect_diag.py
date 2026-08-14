# -*- coding: utf-8 -*-
"""一键收集排障信息：日志 + 失败截图 + 配置，打包成 zip 供反馈使用
用法：双击 收集排障信息.bat（本脚本由 bat 调用）
"""
import os, sys, shutil, zipfile, glob
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))  # 软件根目录

def collect():
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_zip = os.path.join(BASE, '排障信息_' + stamp + '.zip')
    tmp = os.path.join(BASE, '_diag_' + stamp)
    os.makedirs(tmp, exist_ok=True)
    got = []

    def grab(src_rel, dst_name=None):
        src = os.path.join(BASE, src_rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmp, dst_name or os.path.basename(src)))
            got.append(src_rel)
        elif os.path.isdir(src):
            shutil.copytree(src, os.path.join(tmp, dst_name or os.path.basename(src)), dirs_exist_ok=True)
            got.append(src_rel + '/')

    # 1) GUI 运行日志（最近 3 个）
    logs = sorted(glob.glob(os.path.join(BASE, 'logs', 'log-*.log')))[-3:]
    for l in logs:
        shutil.copy2(l, os.path.join(tmp, 'logs-' + os.path.basename(l)))
    got.append('logs/*.log (最近3个)')
    # 2) MaaFramework 底层识别日志
    grab('debug/maafw.log', 'maafw.log')
    # 3) 失败自动截图（最近 30 张）
    errs = sorted(glob.glob(os.path.join(BASE, 'debug', 'on_error', '*.png')))[-30:]
    os.makedirs(os.path.join(tmp, 'on_error'), exist_ok=True)
    for e in errs:
        shutil.copy2(e, os.path.join(tmp, 'on_error', os.path.basename(e)))
    got.append('debug/on_error/*.png (最近' + str(len(errs)) + '张)')
    # 4) agent 日志
    grab('agent/debug/maafw.log', 'agent_maafw.log')
    # 5) 配置文件
    grab('config/config.json', 'config.json')
    grab('config/maa_option.json', 'maa_option.json')
    for f in glob.glob(os.path.join(BASE, 'config', 'instances', '*.json')):
        shutil.copy2(f, os.path.join(tmp, 'instance_' + os.path.basename(f)))
    grab('interface.json', 'interface.json')
    grab('appsettings.json', 'appsettings.json')

    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(tmp):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, tmp))
    shutil.rmtree(tmp, ignore_errors=True)

    print('=' * 52)
    print('排障信息收集完成！')
    print('已收集：')
    for g in got:
        print('  -', g)
    print()
    print('生成文件：')
    print('  ' + out_zip)
    print()
    print('请把这个 zip 文件发给开发者/AI，并说明卡在哪个界面或步骤。')
    print('（如果还能看到游戏界面，建议再补一张模拟器当前画面的截图）')
    print('=' * 52)
    return out_zip

if __name__ == '__main__':
    collect()
