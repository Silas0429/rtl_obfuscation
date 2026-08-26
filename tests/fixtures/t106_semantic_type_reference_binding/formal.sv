module t106_formal_left (
    input logic [1:0] data_i,
    output logic data_o
);
    typedef struct packed {
        logic a;
        logic b;
    } shared_t;

    typedef union packed {
        logic [1:0] raw;
        logic [1:0] pair;
    } shared_u;

    shared_t value;
    shared_u union_value;

    function automatic shared_t make_value(input logic [1:0] value_i);
        make_value = shared_t'(value_i);
    endfunction

    always_comb begin
        value = make_value(data_i);
        union_value = shared_u'(data_i);
    end

    assign data_o = value.a ^ value.b ^ union_value.raw[0];
endmodule

module t106_formal_right (
    input logic [1:0] data_i,
    output logic data_o
);
    typedef struct packed {
        logic a;
        logic b;
    } shared_t;

    typedef union packed {
        logic [1:0] raw;
        logic [1:0] pair;
    } shared_u;

    shared_t value;
    shared_u union_value;

    function automatic shared_t make_value(input logic [1:0] value_i);
        make_value = shared_t'(value_i);
    endfunction

    always_comb begin
        value = make_value(data_i);
        union_value = shared_u'(data_i);
    end

    assign data_o = value.a ^ value.b ^ union_value.raw[0];
endmodule

module t106_top (
    input logic [1:0] data_i,
    output logic data_o
);
    logic left_o;
    logic right_o;
    logic [1:0] stress_o;

    t106_formal_left u_left (
        .data_i(data_i),
        .data_o(left_o)
    );
    t106_formal_right u_right (
        .data_i(data_i),
        .data_o(right_o)
    );

`ifndef FORMAL
    t106_stress u_stress (
        .data_i(data_i),
        .data_o(stress_o)
    );
`else
    assign stress_o = '0;
`endif

    assign data_o = left_o ^ right_o ^ stress_o[0];
endmodule
