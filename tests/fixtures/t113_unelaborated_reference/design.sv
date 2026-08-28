// T113 unelaborated-reference fixture.  Every shape below is required by the
// task contract section 6:
//
//   * a *defined* submodule instantiated only inside an untaken generate branch,
//     whose connection actuals reference a port and an internal signal of the
//     parent -- scenario C of T112 section 14.2, where PySlang builds an
//     `UninstantiatedDefSymbol`, binds no actual, and reports no error at all;
//   * in that same parent, a port and a signal referenced only from live code,
//     which must still rename, so the preserve stays per record;
//   * a design unit that is never elaborated, spelling a name that a live symbol
//     also uses, so the first dead-region shape triggers the same preserve;
//   * a Yosys-readable formal cone, which is formal_cone.sv.
//
// No identifier of this design is written inside any comment, so a byte search
// for one finds only real code.

interface t113_if;
    logic       req;
    logic       ack;
    logic [3:0] tag;
    modport Master (output req, input ack, input tag);
    modport Slave  (input req, output ack, output tag);
endinterface

typedef struct packed {
    logic [3:0] cmd;
    logic       ok;
} t113_word_t;

// --- dead-region shape A: a design unit that is never elaborated -----------
//
// This module is instantiated only from the untaken generate branch of
// t113_branch, so PySlang never treats it as a hierarchy root and never creates
// an `InstanceBodySymbol` for it.  Its whole declaration span is therefore dead
// source: none of the identifiers written here can carry a semantic reference.
module t113_dead_leaf (
    input  logic d_in,
    output logic d_out
);
    logic shared_probe;

    assign shared_probe = d_in;
    assign d_out        = shared_probe;
endmodule

// --- dead-region shape B: an untaken generate branch in a live unit --------
module t113_branch #(
    parameter bit USE_DEAD = 1'b0
) (
    input  logic live_i,
    output logic live_o,
    output logic dead_port_o
);
    logic dead_signal;
    logic live_signal;

    assign live_signal = ~live_i;
    assign live_o      = live_signal;
    assign dead_port_o = 1'b0;

    generate
        if (USE_DEAD) begin : g_dead
            // Both actuals below are physically written and semantically
            // invisible.  dead_port_o also has a live driver above, so it holds
            // complete live binding evidence and must still be preserved.
            t113_dead_leaf u_dead (
                .d_in (dead_signal),
                .d_out(dead_port_o)
            );
        end
    endgenerate
endmodule

// The live owner of the spelling that dead source also uses.  private_probe is
// live and unique, so the two records of this module must split: one preserved,
// one renamed.
module t113_shared_user (
    input  logic       s_in,
    input  t113_word_t s_word,
    output logic       s_out
);
    logic shared_probe;
    logic private_probe;

    assign shared_probe  = s_in;
    assign private_probe = ~s_in;
    assign s_out         = shared_probe ^ private_probe ^ s_word.ok
                           ^ (s_word.cmd != 4'h0);
endmodule

module t113_struct_user (
    input  logic [3:0] cmd_i,
    input  logic       ok_i,
    output logic       bit_o
);
    t113_word_t word;

    always_comb begin
        word     = '0;
        word.cmd = cmd_i;
        word.ok  = ok_i;
    end

    assign bit_o = word.ok ^ (word.cmd != 4'h0);
endmodule

module t113_if_user (
    t113_if            plain_port,
    input  logic       drive_i,
    input  logic [3:0] tag_i,
    output logic       out_bit
);
    assign plain_port.req = drive_i;
    assign plain_port.ack = drive_i;
    assign plain_port.tag = tag_i;
    assign out_bit = plain_port.req ^ plain_port.ack ^ (plain_port.tag != 4'h0);
endmodule

module t113_mp_user (
    t113_if.Master mp_port,
    output logic   out_bit
);
    assign out_bit = 1'b1;
endmodule

module t113_top (
    input  logic       clk,
    input  logic       in_a,
    input  logic       in_b,
    input  logic [3:0] in_cmd,
    output logic       out_y,
    output logic       out_branch,
    output logic       out_shared,
    output logic       out_struct,
    output logic       out_if
);
    t113_if     bus0();
    t113_if     bus1();
    t113_word_t word;
    logic       branch_live;
    logic       branch_dead;
    logic       shared_bit;
    logic       struct_bit;
    logic       if_bit;
    logic       mp_bit;

    always_comb begin
        word     = '0;
        word.cmd = in_cmd;
        word.ok  = in_a;
    end

    t113_formal_top u_formal (
        .clk(clk),
        .in_a(in_a),
        .in_b(in_b),
        .out_y(out_y)
    );

    t113_branch u_branch (
        .live_i(in_a),
        .live_o(branch_live),
        .dead_port_o(branch_dead)
    );

    t113_shared_user u_shared (
        .s_in(in_b),
        .s_word(word),
        .s_out(shared_bit)
    );

    t113_struct_user u_struct (
        .cmd_i(in_cmd),
        .ok_i(in_a),
        .bit_o(struct_bit)
    );

    t113_if_user u_if_user (
        .plain_port(bus0),
        .drive_i(in_a),
        .tag_i(in_cmd),
        .out_bit(if_bit)
    );

    t113_mp_user u_mp_user (
        .mp_port(bus1),
        .out_bit(mp_bit)
    );

    assign out_branch = branch_live ^ branch_dead;
    assign out_shared = shared_bit;
    assign out_struct = struct_bit;
    assign out_if     = if_bit ^ mp_bit;
endmodule
