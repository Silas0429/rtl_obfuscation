module t105_formal_child (
    input logic [1:0] data_i,
    output logic data_o
);
    typedef struct packed {
        logic hi;
        logic lo;
    } t105_formal_pair_t;

    t105_formal_pair_t pair;

    always_comb begin
        pair = {data_i[1], data_i[0]};
    end

    assign data_o = pair.hi ^ pair.lo;
endmodule

module t105_top (
    input logic [1:0] data_i,
    output logic data_o
);
    logic formal_o;
    logic [1:0] stress_o;

    t105_formal_child u_formal (
        .data_i(data_i),
        .data_o(formal_o)
    );

`ifndef FORMAL
    t105_conversion_probe u_probe (
        .data_i(data_i),
        .data_o(stress_o)
    );
`else
    assign stress_o = '0;
`endif

    assign data_o = formal_o ^ stress_o[0];
endmodule
