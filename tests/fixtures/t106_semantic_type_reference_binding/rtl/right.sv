package t106_right_pkg;
    typedef struct packed {
        logic leaf;
    } member_t;

    typedef struct packed {
        member_t nested;
        logic flag;
    } shared_t;

    typedef union packed {
        logic [1:0] raw;
        logic [1:0] pair;
    } shared_u;
endpackage

module t106_right (
    input t106_right_pkg::shared_t typed_i,
    output logic [1:0] out_o
);
    import t106_right_pkg::*;

    shared_t value;
    shared_u union_value;

    function automatic shared_t make_value(input member_t member_i);
        make_value = shared_t'({member_i.leaf, member_i.leaf});
    endfunction

    always_comb begin
        value = make_value('{leaf: typed_i.flag});
        union_value = shared_u'(typed_i);
    end

    assign out_o = {value.flag, union_value.raw[0]};
endmodule
