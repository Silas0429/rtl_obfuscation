interface t109_if;
    logic valid;
    modport master (output valid);
endinterface

typedef struct packed {
    logic a;
    logic b;
} t109_inner_t;

typedef struct packed {
    t109_inner_t a;
    logic [7:0]  user;
} t109_outer_t;

module t109_leaf (
    input  logic a_first,
    input  logic b_second,
    output logic c_third
);
    assign c_third = a_first ^ b_second;
endmodule

// Server root cause 2: a modport-qualified interface port header.
// PySlang exposes this as InterfacePortHeaderSyntax, which has no dataType.
module t109_modport_port (t109_if.master mp_port, output logic o);
    assign mp_port.valid = 1'b1;
    assign o = 1'b0;
endmodule

// Server root cause 3: a struct member followed by a part-select.
// MemberAccessExpression.syntax is None for data.user, while data.a.a keeps
// its ScopedNameSyntax; both must be attributed by the same rule.
// data.a.a also proves nested equal spellings resolve to distinct symbols.
module t109_select_owner (input logic clk, output logic q);
    t109_outer_t data;
    always_comb data = '0;
    assign q = (data.user[3:0] != 4'b0) ? data.a.a : (data.a.b ^ clk);
endmodule

module t109_top (input logic clk, output logic result);
    t109_if if0();
    logic leaf_out;
    logic sel;
    logic mp_out;
    logic sel_q;

    // Server root cause 1: named port connections written in an order that
    // differs from the port declaration order, so pairing two independent
    // lists by index misattributes every label.
    t109_leaf u_leaf (
        .c_third(leaf_out),
        .b_second(clk),
        .a_first(sel)
    );

    t109_modport_port u_mp (.mp_port(if0), .o(mp_out));
    t109_select_owner u_sel (.clk(clk), .q(sel_q));

    assign sel = 1'b0;
    assign result = leaf_out ^ mp_out ^ sel_q ^ if0.valid;
endmodule
