// T115 name-completeness fixture.  Task contract section 5 requires two
// mutually independent shapes plus a Yosys-readable cone:
//
//   * shape one, the known fail-open recorded in token_first_binding.md section
//     2.1: one typedef is used both as a variable type -- which puts it in the
//     top closure and makes it a rename candidate -- and as the member type of a
//     second aggregate.  The member-type position produces a NamedType syntax
//     node that PySlang binds to no reference node at all and reports no issue
//     for, so before this task the declaration was renamed on its own and the
//     rewritten gate stopped compiling;
//   * shape two, which must not be caught: a second typedef of the same core
//     group, every physical token of which is attributed, so it must keep
//     renaming and prove the preserve is per record rather than per group;
//   * the four core groups, each with at least one record that keeps renaming;
//   * a Yosys-readable formal cone, which is formal_cone.sv.
//
// This design contains no dead source at all: no untaken generate branch and no
// design unit that fails to elaborate.  That is deliberate, because it makes the
// T113 rule unable to fire here, so shape one can only be preserved by the new
// name-completeness criterion.
//
// No identifier of this design is written inside any comment, so a byte search
// for one finds only real code.

interface t115_if;
    logic       req;
    logic       ack;
    logic [3:0] tag;
    modport Master (output req, input ack, input tag);
    modport Slave  (input req, output ack, output tag);
endinterface

// --- shape one: also used as the member type of the aggregate below ---------
typedef struct packed {
    logic [3:0] cmd;
} t115_inner_t;

// --- shape two: every physical token of this name is attributed -------------
typedef struct packed {
    t115_inner_t inner;
    logic [3:0]  wide;
} t115_word_t;

module t115_word_user (
    input  logic [3:0] cmd_i,
    output logic [3:0] wide_o,
    output logic [3:0] inner_o
);
    t115_word_t  word;
    t115_inner_t plain;

    always_comb begin
        word           = '0;
        word.inner.cmd = cmd_i;
        word.wide      = cmd_i;
        plain.cmd      = cmd_i;
    end

    assign wide_o  = word.wide;
    assign inner_o = word.inner.cmd ^ plain.cmd;
endmodule

module t115_signal_user (
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic blend;
    logic pick;

    assign blend = in_a & in_b;
    assign pick  = in_a ^ in_b;
    assign out_y = blend | pick;
endmodule

module t115_if_user (
    t115_if            plain_port,
    input  logic       drive_i,
    input  logic [3:0] tag_i,
    output logic       out_bit
);
    assign plain_port.req = drive_i;
    assign plain_port.ack = drive_i;
    assign plain_port.tag = tag_i;
    assign out_bit = plain_port.req ^ plain_port.ack ^ (plain_port.tag != 4'h0);
endmodule

module t115_mp_user (
    t115_if.Master mp_port,
    output logic   out_bit
);
    assign out_bit = 1'b1;
endmodule

module t115_top (
    input  logic       clk,
    input  logic       in_a,
    input  logic       in_b,
    input  logic [3:0] in_cmd,
    output logic       out_y,
    output logic       out_signal,
    output logic [3:0] out_wide,
    output logic [3:0] out_inner,
    output logic       out_if
);
    t115_if bus0();
    t115_if bus1();
    logic       signal_bit;
    logic [3:0] wide_bus;
    logic [3:0] inner_bus;
    logic       if_bit;
    logic       mp_bit;

    t115_formal_top u_formal (
        .clk(clk),
        .in_a(in_a),
        .in_b(in_b),
        .out_y(out_y)
    );

    t115_signal_user u_signal (
        .in_a(in_a),
        .in_b(in_b),
        .out_y(signal_bit)
    );

    t115_word_user u_word (
        .cmd_i(in_cmd),
        .wide_o(wide_bus),
        .inner_o(inner_bus)
    );

    t115_if_user u_if_user (
        .plain_port(bus0),
        .drive_i(in_a),
        .tag_i(in_cmd),
        .out_bit(if_bit)
    );

    t115_mp_user u_mp_user (
        .mp_port(bus1),
        .out_bit(mp_bit)
    );

    assign out_signal = signal_bit;
    assign out_wide   = wide_bus;
    assign out_inner  = inner_bus;
    assign out_if     = if_bit ^ mp_bit;
endmodule
