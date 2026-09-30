/* 26092426: persistent random Bindkey extension; fixed stock hook addresses. */
SECTIONS {
 .guard        0x1e2a454 : { *(.guard) }
 .scanrsp      0x1e2a4a0 : { *(.scanrsp) }
 .capture      ALIGN(4) : { *(.capture) }
 .a6           ALIGN(4) : { *(.a6) }
 .a2           ALIGN(4) : { *(.a2) }
 .lock         ALIGN(4) : { *(.lock) }
 .crypto       ALIGN(4) : { *(.crypto) }
 .cdata        ALIGN(4) : { *(.cdata) }
 .aes          ALIGN(4) : { *(.aes) }
 .rxshim       ALIGN(4) : { *(.rxshim) }
 .rxcode       ALIGN(4) : { *(.rxcode) }
 .rxconst      ALIGN(4) : { *(.rxconst) }
 .frame_hook   0x1e03256 : { *(.frame_hook) }
 .scanrsp_hook 0x1e10a48 : { *(.scanrsp_hook) }
 .a6_branch    0x1e012f0 : { *(.a6_branch) }
 .a2_hook      0x1e01250 : { *(.a2_hook) }
 .fe_fix       0x1e0168c : { *(.fe_fix) }
 .start_hook   0x1e02110 : { *(.start_hook) }
 .rx_report_hook 0x1e04c82 : { *(.rx_report_hook) }
 .version      0x1e07a2a : { *(.version) }
 .unexpected : { *(.text*) *(.rodata*) *(.data*) *(.bss*) *(COMMON) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.llvm_addrsig) }
}
stock_memcpy = 0x2106ee4;
stock_rsp = 0x1e247a4;
stock_scanrsp = 0x1e247fa;
light_read = 0x1e01d2c;
adc_get_voltage = 0x1e00834;
COMMAND = 0x1e0d4e4;
stock_report_mode = 0x1e023a2;
stock_timer_add = 0x1e14cbe;
stock_malloc = 0x1e137d6;
stock_free = 0x1e13824;
vm_read = 0x1e08b20;
vm_write = 0x1e08bec;
a6_low_continue = 0x1e012f8;
a6_responder = 0x1e018bc;
a6_reject_path = 0x1e01752;
a2_error_path = 0x1e01782;
a2_success = 0x1e01894;
stock_factory_defaults = 0x1e00f10;
stock_random_fill = 0x1e24f62;

ASSERT(SIZEOF(.guard)==66,"guard size changed")
ASSERT(SIZEOF(.scanrsp)<=192,"scanrsp overflow")
ASSERT(SIZEOF(.capture)<=64,"capture overflow")
ASSERT(SIZEOF(.a6)<=160,"a6 overflow")
ASSERT(SIZEOF(.a2)<=96,"a2 overflow")
ASSERT(SIZEOF(.lock)<=128,"lock overflow")
ASSERT(SIZEOF(.crypto)<=8192,"crypto overflow")
ASSERT(SIZEOF(.cdata)<=96,"cdata overflow")
ASSERT(SIZEOF(.aes)<=256,"aes overflow")
ASSERT(SIZEOF(.rxshim)<=32,"rx shim overflow")
ASSERT(SIZEOF(.rxcode)<=2048,"rx control overflow")
ASSERT(SIZEOF(.rxconst)==16,"rx domain label width")
ASSERT(SIZEOF(.frame_hook)==4,"frame hook width")
ASSERT(SIZEOF(.scanrsp_hook)==4,"scanrsp hook width")
ASSERT(SIZEOF(.a6_branch)==4,"a6 branch width")
ASSERT(SIZEOF(.a2_hook)==4,"A2 hook width")
ASSERT(SIZEOF(.fe_fix)==4,"fe fix width")
ASSERT(SIZEOF(.start_hook)==4,"start hook width")
ASSERT(SIZEOF(.rx_report_hook)==4,"RX report hook width")
ASSERT(SIZEOF(.version)==38,"version block width")
ASSERT(SIZEOF(.unexpected)==0,"unexpected allocated section")
