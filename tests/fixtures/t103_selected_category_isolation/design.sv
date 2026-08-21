interface t103_cfg_if;
    logic [3:0] qaddr;
endinterface

module t103_top (
    output logic [3:0] data_o
);
    t103_cfg_if cfg_i_if();
    localparam int REG_AW = 4;
    logic [REG_AW-1:0] payload;

    assign payload = cfg_i_if.qaddr;
    assign data_o = payload;
endmodule
