typedef struct packed {
    logic hi;
    logic lo;
} t105_pair_t;

typedef union packed {
    logic [1:0] raw;
    logic [1:0] pair;
} t105_payload_t;

module t105_child (
    input t105_pair_t child_i,
    output logic [1:0] child_o
);
    assign child_o = {child_i.hi, child_i.lo};
endmodule

module t105_conversion_probe (
    input logic [1:0] data_i,
    output logic [1:0] data_o
);
    assign data_o = data_i;

    t105_pair_t explicit_pair;
    t105_pair_t pair_implicit;
    t105_pair_t pair_literal;
    t105_payload_t payload;
    logic [1:0] child_o;

    always_comb begin
        pair_implicit = {data_i[1], data_i[0]};
        pair_literal = 2'b01;
        payload = data_i;
        explicit_pair = t105_pair_t'(data_i);
    end

    t105_child u_child (
        .child_i({data_i[1], data_i[0]}),
        .child_o(child_o)
    );

    assign data_o = {pair_implicit.hi, pair_implicit.lo}
                  ^ pair_literal
                  ^ child_o
                  ^ payload.raw
                  ^ {explicit_pair.hi, explicit_pair.lo};
endmodule
