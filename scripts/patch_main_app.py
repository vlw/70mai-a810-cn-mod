#!/usr/bin/env python3
"""Patch 70mai A810 PRO (DR2830 CN) main_app 1.6.49: features are chosen on the command line.

Features: LANGUAGE_MENU TIMEZONE_MENU DEFAULT_ENGLISH GPS_HOME HLG RU_LABELS, option DEFAULT_TZ=+3.
Notes for the language part:

What it changes (VA = file offset + 0x10000):
 1. Boot no longer forces Chinese: the main boot path called ui_set_language_table(26);
    it now calls a stub that reads param 23 (UI language) and passes it instead.
 2. System settings item "Download App" (page 0x2e) now opens the stock language page 0x40
    in "opened from settings" mode (entry source = page 0x22), like the WW firmware does.
 3. That item's label string id 0x29 ("Download App") -> 0xd0 ("System language").
Stub code lives in the zero padding between .fini and .rodata (single RWX PT_LOAD).
The factory-mode path (0x42874) is left untouched.

Usage: patch_main_app.py IN OUT FEATURE... [DEFAULT_TZ=+3]
"""
import hashlib, struct, sys

B = 0x10000
SRC_MD5 = '0fa96a21bebfc9b7fcf8134d744c8dfd'

PARAM_GET = 0x48ca0            # XA_ParamMng_SingleParamGet(id)
SET_LANG_TABLE = 0x96c58       # ui_set_language_table(param_value)
PAGE_OPEN = 0x96878            # ui_page_open(page_id, arg)
LANG_ENTRY_SET = 0xefb24       # *entry_source = r0 (language page returns to it)
PARAM_LANGUAGE = 0x17
PAGE_SYSTEM_SETTING = 0x22
PAGE_LANGUAGE = 0x40

CAVE = 0xd37848                # .fini end; .rodata starts at 0xd37880
STUB_BOOT = CAVE
STUB_MENU = CAVE + 0x14

def b(src, dst, link):
    off = (dst - (src + 8)) >> 2
    assert -(1 << 23) <= off < (1 << 23)
    return (0xEB000000 if link else 0xEA000000) | (off & 0xFFFFFF)

NOP = 0xE1A00000  # mov r0, r0

stub = [
    # STUB_BOOT: ui_set_language_table(ParamGet(23))
    (STUB_BOOT + 0x00, 0xE92D4010),                              # push {r4, lr}
    (STUB_BOOT + 0x04, 0xE3A00000 | PARAM_LANGUAGE),             # mov r0, #0x17
    (STUB_BOOT + 0x08, b(STUB_BOOT + 0x08, PARAM_GET, True)),    # bl ParamGet
    (STUB_BOOT + 0x0c, 0xE8BD4010),                              # pop {r4, lr}
    (STUB_BOOT + 0x10, b(STUB_BOOT + 0x10, SET_LANG_TABLE, False)),  # b ui_set_language_table
    # STUB_MENU (r1 = page arg from caller): entry_source = 0x22; ui_page_open(0x40, r1)
    (STUB_MENU + 0x00, 0xE92D4002),                              # push {r1, lr}
    (STUB_MENU + 0x04, 0xE3A00000 | PAGE_SYSTEM_SETTING),        # mov r0, #0x22
    (STUB_MENU + 0x08, b(STUB_MENU + 0x08, LANG_ENTRY_SET, True)),   # bl entry_source_set
    (STUB_MENU + 0x0c, 0xE8BD4002),                              # pop {r1, lr}
    (STUB_MENU + 0x10, 0xE3A00000 | PAGE_LANGUAGE),              # mov r0, #0x40
    (STUB_MENU + 0x14, b(STUB_MENU + 0x14, PAGE_OPEN, False)),   # b ui_page_open
]

# Fix for v1 freeze: after a language is picked from settings, CN only closed the page
# (nothing underneath -> frozen last camera frame). WW instead refreshes language
# resources and reopens system settings: do the same.
LANG_REFRESH = 0x98440         # CN twin of WW 0x9a300 (reload fonts/labels if param 23 changed)
ENTER_TAIL = 0xefc1c           # language page event cb epilogue (unlock + return)
FOCUS_ITEM = 5                 # settings item we turned into "System language"
CAVE2 = 0x19a4e50              # zero gap between .eh_frame and .init_array (same RWX PT_LOAD)
reopen = [
    0xE24DD018,                                  # sub sp, sp, #0x18
    0xE3A03000, 0xE58D3000,                      # [sp]      = 0
    0xE3A03001, 0xE58D3004,                      # [sp+4]    = 1
    0xE3A03000 | FOCUS_ITEM, 0xE58D3008,         # [sp+8]    = focused item
    0xE3A03000, 0xE58D300C, 0xE58D3010, 0xE58D3014,  # [sp+0xc..0x14] = 0
    None,                                        # bl LANG_REFRESH
    0xE1A0100D,                                  # mov r1, sp
    0xE3A00000 | PAGE_SYSTEM_SETTING,            # mov r0, #0x22
    None,                                        # bl ui_page_open
    0xE28DD018,                                  # add sp, sp, #0x18
    None,                                        # b ENTER_TAIL
]
reopen[11] = b(CAVE2 + 4 * 11, LANG_REFRESH, True)
reopen[14] = b(CAVE2 + 4 * 14, PAGE_OPEN, True)
reopen[16] = b(CAVE2 + 4 * 16, ENTER_TAIL, False)
stub += [(CAVE2 + 4 * i, w) for i, w in enumerate(reopen)]

def bne(src, dst):
    return 0x10000000 | (b(src, dst, False) & 0x0FFFFFFF)

def movw(rd, imm):
    return 0xE3000000 | ((imm >> 12) & 0xF) << 16 | rd << 12 | (imm & 0xFFF)

def movt(rd, imm):
    return 0xE3400000 | ((imm >> 12) & 0xF) << 16 | rd << 12 | (imm & 0xFFF)

# Time zone (v5): CN "System time" page (0x29) has no time-zone item; the stock zone page 0x2a
# exists but is unreachable, so GPS sync applies the factory UTC+8. With GPS sync on, item 0
# ("calibrate time manually", useless then) becomes "Select time zone" and opens page 0x2a.
PARAM_GPS_TIME = 0x16          # param 22: GPS time sync on/off
PARAM_TIMEZONE = 0x14          # param 20: zone enum 1..35 (27 = UTC+8)
PAGE_TIME = 0x29
PAGE_TIMEZONE = 0x2a
PAGE_RET_SET = 0x9645c         # ui_page_set_return(page, arg) used before opening a subpage
LABEL_SET = 0x952f8            # lv_plugin label set text by string id
STR_CALIBRATE, STR_SELECT_TZ = 0xa6, 0xaa
ITEM0_LABEL_PTR = 0x1b39e2c    # time page: item 0 label object (fp array base, stride 0x10)
TIME_ENTER_ITEM0 = 0xda108     # ENTER on item 0: 'mov r1, r4' then dialog/open 0x42
TIME_HANDLER_TAIL = 0xd9ed4    # time page key handler epilogue (unlock, return)
TIME_TOGGLE_RET = 0xda0b4      # 'b TIME_HANDLER_TAIL' right after the GPS toggle (0xd9288)
TIME_LABEL_LDRH = 0xd9a3c      # item build: 'ldrh r1, [sb, #-0x24]' (label id) before LABEL_SET
LDRH_R1_SB_M24 = 0xE15912B4    # ldrh r1, [sb, #-0x24]
CAVE3 = 0x19a4ea0
tz_enter = [                                        # A: ENTER on item 0
    0xE3A00000 | PARAM_GPS_TIME,                    # mov r0, #0x16
    'bl', PARAM_GET,
    0xE3500000,                                     # cmp r0, #0
    ('bne', 6),                                     # -> tz path (index 6 below)
    0xE1A01004,                                     # mov r1, r4   (original instruction)
    'b', TIME_ENTER_ITEM0 + 4,                      # resume stock manual-calibration path
    0xE3A00000 | PARAM_TIMEZONE,                    # [6] mov r0, #0x14
    'bl', PARAM_GET,
    0xE2500001,                                     # subs r0, r0, #1   (list focus = enum-1)
    0x43A00000,                                     # movmi r0, #0
    0xE58D0014,                                     # str r0, [sp, #0x14]
    0xE3A03000, 0xE58D300C, 0xE58D3018, 0xE58D301C, # [sp+0xc],[0x18],[0x1c] = 0
    0xE3A03001, 0xE58D3010,                         # [sp+0x10] = 1
    0xE3A01000,                                     # mov r1, #0
    0xE3A00000 | PAGE_TIME,                         # mov r0, #0x29
    'bl', PAGE_RET_SET,
    0xE28D100C,                                     # add r1, sp, #0xc
    0xE3A00000 | PAGE_TIMEZONE,                     # mov r0, #0x2a
    'bl', PAGE_OPEN,
    'b', TIME_HANDLER_TAIL,
]
tz_label = [                                        # B: label id while building items
    LDRH_R1_SB_M24,                                 # ldrh r1, [sb, #-0x24]
    0xE3510000 | STR_CALIBRATE,                     # cmp r1, #0xa6
    0x112FFF1E,                                     # bxne lr
    0xE92D4002,                                     # push {r1, lr}
    0xE3A00000 | PARAM_GPS_TIME,                    # mov r0, #0x16
    'bl', PARAM_GET,
    0xE8BD4002,                                     # pop {r1, lr}
    0xE3500000,                                     # cmp r0, #0
    0x13A01000 | STR_SELECT_TZ,                     # movne r1, #0xaa
    0xE12FFF1E,                                     # bx lr
]
tz_toggle = [                                       # C: relabel item 0 right after GPS toggle
    movw(0, ITEM0_LABEL_PTR & 0xFFFF),
    movt(0, ITEM0_LABEL_PTR >> 16),
    0xE5904000,                                     # ldr r4, [r0]
    0xE3540000,                                     # cmp r4, #0
    ('beq', 12),                                    # -> tail (instruction index, not list index)
    0xE3A00000 | PARAM_GPS_TIME,                    # mov r0, #0x16
    'bl', PARAM_GET,
    0xE3500000,                                     # cmp r0, #0
    0x13A01000 | STR_SELECT_TZ,                     # movne r1, #0xaa
    0x03A01000 | STR_CALIBRATE,                     # moveq r1, #0xa6
    0xE1A00004,                                     # mov r0, r4
    'bl', LABEL_SET,
    'b', TIME_HANDLER_TAIL,                         # [12]
]

TIME_UPGRADE_LDRH = 0xd9090    # focus/upgrade refresh: 'ldrh r1, [r7, #8]' (r0 = label obj, live)
LDRH_R1_R7_8 = 0xE1D710B8      # ldrh r1, [r7, #8]
tz_label_refresh = [                                # D: same rule when labels are re-set on focus moves
    LDRH_R1_R7_8,                                   # ldrh r1, [r7, #8]
    0xE3510000 | STR_CALIBRATE,                     # cmp r1, #0xa6
    0x112FFF1E,                                     # bxne lr
    0xE92D4007,                                     # push {r0, r1, r2, lr}  (r0 = label object)
    0xE3A00000 | PARAM_GPS_TIME,                    # mov r0, #0x16
    'bl', PARAM_GET,
    0xE3500000,                                     # cmp r0, #0
    0xE8BD4007,                                     # pop {r0, r1, r2, lr}  (flags kept)
    0x13A01000 | STR_SELECT_TZ,                     # movne r1, #0xaa
    0xE12FFF1E,                                     # bx lr
]

# v6: language list tail. CN dropped Filipino from the 21-row WW list (table 0x19db9ac, 0x20/row,
# value at +0x1c) but kept the list size (21) and ENTER saved the row *position* as param 23:
# Italiano->17 (falls back to English), Türkçe->18 (Italian), row 19 'عربي'->Arabic UI the single
# CN font cannot draw (all text blank), row 20 empty->Turkish. Fix: save the row's value, 19 rows.
LANG_LIST_VALUES = 0x19db9ac + 0x1c
LANG_ENTER_MOV = 0xefbe8       # 'mov r1, r0' (r0 = selected position) before ParamSet(23, r1)
LANG_LIST_COUNT = 0xefa8c      # 'mov r1, #0x15' -> list item count passed to the menu-list ctor
lang_value = [                                      # E: r1 = table[r0].value (r0 kept)
    0xE1A01000,                                     # mov r1, r0   (stock behaviour if r0 < 0)
    0xE3500000,                                     # cmp r0, #0
    0xB12FFF1E,                                     # bxlt lr      (no selection: -1)
    movw(1, LANG_LIST_VALUES & 0xFFFF),
    movt(1, LANG_LIST_VALUES >> 16),
    0xE7911280,                                     # ldr r1, [r1, r0, lsl #5]
    0xE12FFF1E,                                     # bx lr
]

# v7: BACK (key 0x15) on the language page only clicked: CN never opens it from settings, so the
# WW branch 'if (src == 0x22) { close; reopen system settings }' (WW 0xe1ab4) is missing.
LANG_BACK_TAIL = 0xefd84       # 'b ENTER_TAIL' after the BACK key press feedback
LANG_SRC = 0x1b4133c           # entry source set by 0xefb24 (0x22 when opened from settings)
CLOSE_TOP = 0x96684            # ui_close_top_page
lang_back = [                                       # F
    movw(3, LANG_SRC & 0xFFFF),
    movt(3, LANG_SRC >> 16),
    0xE5933000,                                     # ldr r3, [r3]
    0xE3530000 | PAGE_SYSTEM_SETTING,               # cmp r3, #0x22
    ('bne_abs', ENTER_TAIL),                        # not from settings: stock (do nothing)
    'bl', CLOSE_TOP,
    'b', CAVE2,                                     # refresh + reopen settings, focus item 5
]

# v9: home page GPS indicator + speed line under the clock.
# UIMng state 0x1a26730: +0xb4 byte = GPS fix (set by DEVMNG_EV_GPS_DETECT_VALID/INVALID),
# +0x124 int = speed as the stock speed screensaver shows it (units label by param 0x29).
GPS_FIX = 0x1a26730 + 0xb4
GPS_SPEED = 0x1a26730 + 0x124
PARAM_UNITS = 0x29
LV_LABEL_CREATE, LV_LABEL_SET_TEXT = 0xb73da4, 0xb7325c
LV_OBJ_SET_HIDDEN, LV_OBJ_SET_POS, LV_OBJ_SET_SIZE = 0xb5a1a0, 0xb5951c, 0xb5af3c
LV_OBJ_ADD_STYLE, LV_LABEL_SET_ALIGN, LV_LABEL_SET_LONG_MODE = 0xb5c734, 0xb71224, 0xb73bc4
LABEL_SET_STATIC = 0xb73b14    # used by the clock updater
SNPRINTF = 0x1bf7c
CLOCK_X, CLOCK_Y, CLOCK_W, CLOCK_H = 0x16f, 0x3c, 0x107, 0x28
HOME_CLOCK_HOOK = 0xad3fc      # 'ldr r3,[pc,#..]' (=0x3e5c) right after the clock label is styled
HOME_CLOCK_UPDATE = 0xafbc8    # 'bl LABEL_SET_STATIC' in the clock updater (runs with the page)
STATUS_GPS_BIT = 0xae990       # 'orrne r6, r6, #4' (GPS bit only with a fix)
STATUS_GPS_SRC = 0xaeb38       # 'ldr r1, [r5, r3]' (r3 = GOT slot of icon 188)
DATA = 0x19a5000               # data area inside the zero gap (RWX segment)
SPEED_LABEL, SPEED_BUF = DATA, DATA + 0x10
FMT_KMH, FMT_MPH = DATA + 0x20, DATA + 0x30
CAVE4 = DATA + 0x40
DIM_DSC = DATA + 0x400         # lv_img_dsc_t of the dimmed GPS icon, pixels follow
ICON188_DSC = 0x19dca68

def asm(base, prog):
    """Assembler with symbolic labels: ('L', name), ('bl'|'b', addr), ('beq'|'bne', name)."""
    labels, pc = {}, 0
    for it in prog:
        if isinstance(it, tuple) and it[0] == 'L':
            labels[it[1]] = base + 4 * pc
        else:
            pc += 1
    out = []
    for it in prog:
        if isinstance(it, tuple) and it[0] == 'L':
            continue
        va = base + 4 * len(out)
        if isinstance(it, tuple) and it[0] in ('bl', 'b'):
            out.append(b(va, it[1], it[0] == 'bl'))
        elif isinstance(it, tuple):
            cond = {'beq': 0x0, 'bne': 0x1, 'bal': 0xE}[it[0]]
            out.append((cond << 28) | (b(va, labels[it[1]], False) & 0x0FFFFFFF))
        else:
            out.append(it)
    return out

def mov_r(rd, rm): return 0xE1A00000 | rd << 12 | rm
def movi(rd, imm): return 0xE3A00000 | rd << 12 | imm  # imm < 256

speed_create = [                                    # G: called instead of 'ldr r3,=0x3e5c'
    0xE92D4037,                                     # push {r0, r1, r2, r4, r5, lr}
    0xE5960000,                                     # ldr r0, [r6]   (clock label -> parent)
    movi(1, 0), ('bl', LV_LABEL_CREATE),
    0xE2504000,                                     # subs r4, r0, #0
    ('beq', 'out'),
    movw(5, SPEED_LABEL & 0xFFFF), movt(5, SPEED_LABEL >> 16),
    0xE5854000,                                     # str r4, [r5]
    mov_r(0, 4), movi(1, 0), mov_r(2, 8), ('bl', LV_OBJ_ADD_STYLE),     # clock style (font/colour)
    mov_r(0, 4), movi(1, 2), ('bl', LV_LABEL_SET_ALIGN),                # right aligned like clock
    mov_r(0, 4), movi(1, 1), ('bl', LV_LABEL_SET_LONG_MODE),            # BREAK: fixed width, so
                                                                        # right align works (EXPAND=0 hugs text)
    mov_r(0, 4), movw(1, CLOCK_X), movi(2, CLOCK_Y + CLOCK_H), ('bl', LV_OBJ_SET_POS),
    mov_r(0, 4), movw(1, CLOCK_W), movi(2, CLOCK_H), ('bl', LV_OBJ_SET_SIZE),
    mov_r(0, 4), movi(1, 1), ('bl', LV_OBJ_SET_HIDDEN),
    ('L', 'out'),
    0xE8BD4037,                                     # pop {r0, r1, r2, r4, r5, lr}
    movw(3, 0x3e5c),                                # replaced instruction's value
    0xE12FFF1E,                                     # bx lr
]
speed_update = [                                    # H: replaces 'bl LABEL_SET_STATIC' in clock updater
    0xE92D4010,                                     # push {r4, lr}
    ('bl', LABEL_SET_STATIC),
    movw(4, SPEED_LABEL & 0xFFFF), movt(4, SPEED_LABEL >> 16),
    0xE5944000,                                     # ldr r4, [r4]
    0xE3540000,                                     # cmp r4, #0
    ('beq', 'done'),
    movw(0, GPS_FIX & 0xFFFF), movt(0, GPS_FIX >> 16),
    0xE5D00000,                                     # ldrb r0, [r0]
    0xE3500000,                                     # cmp r0, #0
    ('beq', 'hide'),
    movi(0, PARAM_UNITS), ('bl', PARAM_GET),
    0xE3500001,                                     # cmp r0, #1   (1 = mph)
    movw(2, FMT_KMH & 0xFFFF),
    0x03000000 | movw(2, FMT_MPH & 0xFFFF) & 0x0FFFFFFF,  # movweq r2, FMT_MPH
    movt(2, FMT_KMH >> 16),
    movw(3, GPS_SPEED & 0xFFFF), movt(3, GPS_SPEED >> 16),
    0xE5933000,                                     # ldr r3, [r3]
    movw(0, SPEED_BUF & 0xFFFF), movt(0, SPEED_BUF >> 16),
    movi(1, 16), ('bl', SNPRINTF),
    mov_r(0, 4), movw(1, SPEED_BUF & 0xFFFF), movt(1, SPEED_BUF >> 16), ('bl', LV_LABEL_SET_TEXT),
    mov_r(0, 4), movi(1, 0), ('bl', LV_OBJ_SET_HIDDEN),
    ('bal', 'done'),
    ('L', 'hide'),
    mov_r(0, 4), movi(1, 1), ('bl', LV_OBJ_SET_HIDDEN),
    ('L', 'done'),
    0xE8BD8010,                                     # pop {r4, pc}
]
icon_src = [                                        # I: r1 = fix ? icon 188 : dimmed icon
    0xE7951003,                                     # ldr r1, [r5, r3]  (replaced instruction)
    movw(12, GPS_FIX & 0xFFFF), movt(12, GPS_FIX >> 16),
    0xE5DCC000,                                     # ldrb ip, [ip]
    0xE35C0000,                                     # cmp ip, #0
    0x112FFF1E,                                     # bxne lr
    movw(1, DIM_DSC & 0xFFFF), movt(1, DIM_DSC >> 16),
    0xE12FFF1E,                                     # bx lr
]

# HLG (experimental): main_app never sets HD_VIDEOENC_PARAM_OUT_VUI, so streams carry no colour
# description. Wrap hd_videoenc_set: after PATH_CONFIG (2) / OUT_ENC_PARAM (5) / OUT_ENC_PARAM2 (27)
# also set OUT_VUI (6) for the same path: HLG (transfer 18, BT.709 primaries/matrix, limited range)
# when the front IMX678 runs the HDR ISP config (whose tone curve hlg_cfg.py makes HLG), else VUI off.
# The rear camera (TP9951 AHD decoder, video already SDR-processed in the camera) is never tagged.
VENC_SET = 0xab9230            # hd_videoenc_set(path_id, param, p)
VENC_PROLOGUE = 0xE92D4FF0     # push {r4, r5, r6, r7, r8, sb, sl, fp, lr}
ISP_LOAD_CFG = 0x8b34ac        # XA_Media_Isp_Load_Cfg(sensor, mode): sensor 0 = IMX678, mode 1 = hdr.cfg
ISP_PROLOGUE = 0xE92D4070      # push {r4, r5, r6, lr}
REAR_OUT = 3                   # low byte of the rear encoder path id (venc out 2, 1920x1080) - checked via log
VUI_MATRIX, VUI_TRANSFER, VUI_PRIMARIES = 1, 18, 1       # BT.709 / ARIB STD-B67 (HLG) / BT.709
VUI_WRAP = 0x19b5000           # own spot in the zero gap, clear of DATA/speed/icon (end 0x19a708c)
VUI_ENTRY = VUI_WRAP + 8       # after the 2-word trampoline to the original body
VUI_STATE = VUI_WRAP + 0x100
# state: +0 IMX678 cfg mode (-1 none yet), +4 last OUT_VUI result, +8 hit count,
#        +0x10 path id log [8] (by path_id & 7), +0x30 HLG struct, +0x48 VUI-off struct (zeros)
vui_wrap = [
    ('L', 'orig'),
    VENC_PROLOGUE, ('b', VENC_SET + 4),              # original entry
    0xE3510005,                                     # cmp r1, #5
    0x1351001B,                                     # cmpne r1, #27
    0x13510002,                                     # cmpne r1, #2  (before start: else the 4K SPS has no VUI)
    ('bne', 'orig'),
    0xE92D4031,                                     # push {r0, r4, r5, lr}
    ('bl', VUI_WRAP),                               # original call, r0-r2 intact
    0xE1A04000,                                     # mov r4, r0
    0xE59D0000,                                     # ldr r0, [sp]   path id
    movw(5, VUI_STATE & 0xFFFF), movt(5, VUI_STATE >> 16),
    0xE2003007, 0xE2852010, 0xE7820103,             # and r3,r0,#7; add r2,r5,#0x10; str r0,[r2,r3,lsl#2]
    0xE2852048,                                     # add r2, r5, #0x48   VUI off
    0xE5953000, 0xE3530001,                         # ldr r3, [r5]; cmp r3, #1   HDR cfg?
    ('bne', 'set'),
    0xE20030FF, 0xE3530000 | REAR_OUT,              # and r3, r0, #0xff; cmp r3, #REAR_OUT
    0x12852030,                                     # addne r2, r5, #0x30  HLG
    ('L', 'set'),
    0xE3A01006,                                     # mov r1, #6  OUT_VUI
    ('bl', VENC_SET),
    0xE5850004, 0xE5953008, 0xE2833001, 0xE5853008, # result, ++hits
    0xE1A00004,                                     # mov r0, r4
    0xE8BD4032,                                     # pop {r1, r4, r5, lr}
    0xE12FFF1E,                                     # bx lr
]
isp_hook = [                                        # remember the IMX678 cfg mode
    movw(12, VUI_STATE & 0xFFFF), movt(12, VUI_STATE >> 16),
    0xE3500000, 0x058C1000,                         # cmp r0, #0; streq r1, [ip]
    ISP_PROLOGUE, ('b', ISP_LOAD_CFG + 4),
]

def assemble(base, prog):
    """Tiny assembler for the lists above: words, ('bl'|'b', target), ('bne'|'beq', insn index)."""
    out, i = [], 0
    while i < len(prog):
        item = prog[i]
        va = base + 4 * len(out)
        if item in ('bl', 'b'):
            out.append(b(va, prog[i + 1], item == 'bl'))
            i += 2
            continue
        if isinstance(item, tuple) and item[0] == 'bne_abs':  # conditional branch to an absolute VA
            out.append(bne(va, item[1]))
        elif isinstance(item, tuple):
            cond = {'bne': 0x1, 'beq': 0x0}[item[0]]
            out.append((cond << 28) | (b(va, base + 4 * item[1], False) & 0x0FFFFFFF))
        else:
            out.append(item)
        i += 1
    return out

TZ_ENTER = CAVE3
_a = assemble(TZ_ENTER, tz_enter)
TZ_LABEL = TZ_ENTER + 4 * len(_a)
_bb = assemble(TZ_LABEL, tz_label)
TZ_TOGGLE = TZ_LABEL + 4 * len(_bb)
_c = assemble(TZ_TOGGLE, tz_toggle)
TZ_LABEL_REFRESH = TZ_TOGGLE + 4 * len(_c)
_d = assemble(TZ_LABEL_REFRESH, tz_label_refresh)
LANG_VALUE = TZ_LABEL_REFRESH + 4 * len(_d)
_e = assemble(LANG_VALUE, lang_value)
LANG_BACK = LANG_VALUE + 4 * len(_e)
_f = assemble(LANG_BACK, lang_back)
_g = asm(VUI_WRAP, vui_wrap)
ISP_HOOK = VUI_WRAP + 4 * len(_g)
_g += asm(ISP_HOOK, isp_hook)
assert VUI_WRAP + 4 * len(_g) <= VUI_STATE
vui_state = [0xFFFFFFFF, 0xFFFFFFFF, 0, 0] + [0] * 8 + [
    1, 0, 0,                                        # vui_en, sar_width, sar_height
    VUI_MATRIX | VUI_TRANSFER << 8 | VUI_PRIMARIES << 16 | 5 << 24,  # mat, tran, prim, video_format=5
    0,                                              # color_range=0 (limited, as the ISP outputs), pad
    0] + [0] * 6                                    # timing_present_flag; then the VUI-off struct
stub_lang = stub                                    # boot/menu stubs + settings reopen (CAVE2)
tz_code = [(TZ_ENTER + 4 * i, w) for i, w in enumerate(_a + _bb + _c + _d)]
lang_code = [(LANG_VALUE + 4 * i, w) for i, w in enumerate(_e + _f)]
assert TZ_ENTER + 4 * len(_a + _bb + _c + _d + _e + _f) <= DATA
hlg_code = [(VUI_WRAP + 4 * i, w) for i, w in enumerate(_g)] + [(VUI_STATE + 4 * i, w) for i, w in enumerate(vui_state)]
assert VUI_STATE + 4 * len(vui_state) <= 0x19b5cd8   # .init_array starts there

SPEED_CREATE = CAVE4
_g = asm(SPEED_CREATE, speed_create)
SPEED_UPDATE = SPEED_CREATE + 4 * len(_g)
_h = asm(SPEED_UPDATE, speed_update)
ICON_SRC = SPEED_UPDATE + 4 * len(_h)
_i = asm(ICON_SRC, icon_src)
assert ICON_SRC + 4 * len(_i) <= DIM_DSC
gps_code = [(SPEED_CREATE + 4 * i, w) for i, w in enumerate(_g + _h + _i)]

def words(va, data):
    data = data + bytes(-len(data) % 4)
    return [(va + i, int.from_bytes(data[i:i + 4], 'little')) for i in range(0, len(data), 4)]

gps_code += words(FMT_KMH, b'%d km/h\0') + words(FMT_MPH, b'%d mph\0')

def dim_icon_words(d):
    """lv_img_dsc_t + ARGB8888 pixels of icon 188 with alpha * 0.35 ('searching')."""
    hdr, size, data = struct.unpack_from('<III', d, ICON188_DSC - B)
    px = bytearray(d[data - B:data - B + size])
    px[3::4] = bytes(a * 35 // 100 for a in px[3::4])
    dsc = struct.pack('<III', hdr, size, DIM_DSC + 12)
    return words(DIM_DSC, dsc + bytes(px))

LABEL_VA, LABEL_OLD, LABEL_NEW = 0x19db7b8, 0x0029, 0x00D0   # settings item 5 label id (u16)

# Time zone enum (param 20) -> UTC offset in minutes, enum = index + 1 (27 = UTC+8, stock default)
TZ_OFFSETS = [-720, -660, -600, -540, -480, -420, -360, -300, -240, -210, -180, -120, -60, 0, 60, 120, 180,
              210, 240, 270, 300, 330, 345, 360, 390, 420, 480, 540, 570, 600, 630, 660, 720, 780, 840]
assert TZ_OFFSETS.index(480) + 1 == 27 and TZ_OFFSETS.index(180) + 1 == 17

def tz_enum(text):
    """'+3', '-5', '+5:30' -> zone enum."""
    sign = -1 if text.startswith('-') else 1
    h, _, m = text.lstrip('+-').partition(':')
    minutes = sign * (int(h) * 60 + int(m or 0))
    assert minutes in TZ_OFFSETS, f'unsupported time zone {text}'
    return TZ_OFFSETS.index(minutes) + 1

def ru_labels():
    # 'Формат кодирования видео' overlaps its value in the menu -> 'Формат видео' (same slot, NUL-padded)
    old = 'Формат кодирования видео'.encode() + bytes(2)
    new = 'Формат видео'.encode().ljust(len(old), b'\0')
    out = [(0x171a9f4 + i, int.from_bytes(old[i:i + 4], 'little'), int.from_bytes(new[i:i + 4], 'little'))
           for i in range(0, len(old), 4)]
    # compression values name the codec; too long for their 28-byte slots, so the strings go to the zero
    # gap after the VUI state and the Russian string-table pointers are redirected
    for n, (ptr, old_str, txt) in enumerate([(0x1a0609c, 0x171aa24, 'Высокое сжатие (HEVC)'),
                                             (0x1a060a4, 0x171aa40, 'Низкое сжатие (AVC)')]):
        va = 0x19b5200 + 0x40 * n
        data = txt.encode() + b'\0'
        assert len(data) <= 0x40
        out += [(a, 0, w) for a, w in words(va, data)] + [(ptr, old_str, va)]
    return out

def features(d, default_tz):
    """Feature name -> [(va, expected original word, new word)]. Code addresses are fixed per feature,
    so any subset gives the same bytes for the features it contains."""
    label_old = struct.unpack_from('<I', d, LABEL_VA - B)[0]
    assert label_old & 0xFFFF == LABEL_OLD, f'label: found {label_old & 0xFFFF:#x}'
    return {
        # language choice in System settings (item 'Download App' -> 'System language'), boot uses param 23
        'LANGUAGE_MENU': [(va, 0, w) for va, w in stub_lang + lang_code] + [
            (0x43004, b(0x43004, SET_LANG_TABLE, True), b(0x43004, STUB_BOOT, True)),  # boot: bl stub
            (0xd6690, 0xE3A0002E, b(0xd6690, STUB_MENU, True)),                        # was mov r0,#0x2e
            (0xd6694, b(0xd6694, PAGE_OPEN, True), NOP),                               # was bl ui_page_open
            (LABEL_VA, label_old, label_old & 0xFFFF0000 | LABEL_NEW),
            (0xefc08, bne(0xefc08, ENTER_TAIL), bne(0xefc08, CAVE2)),  # picked from settings -> reopen settings
            (LANG_ENTER_MOV, 0xE1A01000, b(LANG_ENTER_MOV, LANG_VALUE, True)),   # save the row's value
            (LANG_LIST_COUNT, 0xE3A01015, 0xE3A01013),                           # 21 -> 19 rows
            (LANG_BACK_TAIL, b(LANG_BACK_TAIL, ENTER_TAIL, False), b(LANG_BACK_TAIL, LANG_BACK, False)),
        ],
        # time zone choice on the System time page (item 0 while GPS time sync is on)
        'TIMEZONE_MENU': [(va, 0, w) for va, w in tz_code] + [
            (TIME_ENTER_ITEM0, 0xE1A01004, b(TIME_ENTER_ITEM0, TZ_ENTER, False)),
            (TIME_LABEL_LDRH, LDRH_R1_SB_M24, b(TIME_LABEL_LDRH, TZ_LABEL, True)),
            (TIME_TOGGLE_RET, b(TIME_TOGGLE_RET, TIME_HANDLER_TAIL, False), b(TIME_TOGGLE_RET, TZ_TOGGLE, False)),
            (TIME_UPGRADE_LDRH, LDRH_R1_R7_8, b(TIME_UPGRADE_LDRH, TZ_LABEL_REFRESH, True)),
        ],
        # English (param 23 = 0) instead of Chinese (26) after factory reset and on first boot
        'DEFAULT_ENGLISH': [(0x4ab78, 0x0000001A, 0x00000000),
                            (0xef1c0, 0xE3A0101A, 0xE3A01000)],
        # factory default time zone (params 19..22 literal {1, 27, 0, 1}; GPS time sync stays on)
        'DEFAULT_TZ': [(0x4ab6c, 0x0000001B, default_tz)] if default_tz else [],
        # home page: GPS icon always shown (dim while searching) + speed line under the clock
        'GPS_HOME': [(va, 0, w) for va, w in gps_code + dim_icon_words(d)] + [
            (HOME_CLOCK_HOOK, 0xE59F3458, b(HOME_CLOCK_HOOK, SPEED_CREATE, True)),
            (HOME_CLOCK_UPDATE, b(HOME_CLOCK_UPDATE, LABEL_SET_STATIC, True), b(HOME_CLOCK_UPDATE, SPEED_UPDATE, True)),
            (STATUS_GPS_BIT, 0x13866004, 0xE3866004),                             # orrne -> orr r6,r6,#4
            (STATUS_GPS_SRC, 0xE7951003, b(STATUS_GPS_SRC, ICON_SRC, True)),
        ],
        # HLG colour tag in HDR mode of the front camera (the tone curve comes from hlg_cfg.py)
        'HLG': [(va, 0, w) for va, w in hlg_code] + [
            (VENC_SET, VENC_PROLOGUE, b(VENC_SET, VUI_ENTRY, False)),
            (ISP_LOAD_CFG, ISP_PROLOGUE, b(ISP_LOAD_CFG, ISP_HOOK, False)),
        ],
        'RU_LABELS': ru_labels(),
    }

REQUIRES = {'DEFAULT_ENGLISH': 'LANGUAGE_MENU'}       # boot forces Chinese without the language stub

def main():
    """Usage: patch_main_app.py IN OUT FEATURE... [DEFAULT_TZ=+3]"""
    src, dst = sys.argv[1], sys.argv[2]
    opts = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
    names = [a for a in sys.argv[3:] if '=' not in a]
    d = bytearray(open(src, 'rb').read())
    assert hashlib.md5(d).hexdigest() == SRC_MD5, 'unexpected main_app (need CN 1.6.49)'
    assert STUB_MENU + 0x18 <= 0xd37880
    assert struct.unpack_from('<I', d, HOME_CLOCK_HOOK + 8 + 0x458 - B)[0] == 0x3e5c
    tz = tz_enum(opts['DEFAULT_TZ']) if opts.get('DEFAULT_TZ') else 0
    table = features(d, tz)
    if tz:
        names.append('DEFAULT_TZ')
    for n in names:
        assert n in table, f'unknown feature {n}; known: {", ".join(table)}'
        assert REQUIRES.get(n, n) in names, f'{n} needs {REQUIRES.get(n)}'
    for n in names:
        for va, old, new in table[n]:
            cur, = struct.unpack_from('<I', d, va - B)
            assert cur == old, f'{n} {va:#x}: expected {old:#010x}, found {cur:#010x}'
            struct.pack_into('<I', d, va - B, new)
    open(dst, 'wb').write(d)
    print('main_app:', ' '.join(names) or '(stock)', hashlib.md5(d).hexdigest())

if __name__ == '__main__':
    main()
