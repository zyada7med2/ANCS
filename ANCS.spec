# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller ANCS.spec

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        # GUI assets
        ('network_manager/gui/bg.png', 'network_manager/gui'),
        ('network_manager/gui/logo.png', 'network_manager/gui'),
        ('network_manager/gui/logo_cropped.png', 'network_manager/gui'),
        ('network_manager/gui/logo_icon.png', 'network_manager/gui'),
        ('network_manager/gui/logo.svg', 'network_manager/gui'),
        ('network_manager/gui/ancs_logo.ico', 'network_manager/gui'),
        # SVG icons for device list, buttons, etc.
        ('network_manager/gui/icons', 'network_manager/gui/icons'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'network_manager',
        'network_manager.gui',
        'network_manager.gui.app',
        'network_manager.gui.wizards',
        'network_manager.gui.wizards.config_engine',
        'network_manager.gui.wizards.guided_setup_wizard',
        'network_manager.gui.wizards.vlan_wizard',
        'network_manager.gui.wizards.stp_wizard',
        'network_manager.network',
        'network_manager.models',
        'network_manager.config',
        'network_manager.vendors',
        'network_manager.vendors.base',
        'network_manager.vendors.cisco_ios',
        'network_manager.vendors.huawei_vrp',
        'network_manager.ai_agent',
        'network_manager.gui.agent_dialog',
        'network_manager.gui.agent_bridge',
        'network_manager.gui.deploy_review_dialog',
        'network_manager.gui.template_selector_dialog',
        'network_manager.network.state_snapshot',
        'network_manager.gui.sync_workflows',
        'google.genai',
        'google.genai.types',
    ],
    collect_all=['PySide6'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ANCS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='network_manager/gui/ancs_logo.ico',
)
