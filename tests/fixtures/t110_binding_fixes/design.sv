// T110 binding-fix fixture.  Every shape below is required by the task
// contract: reordered named port connections, `.*` and positional connections,
// modport-qualified and plain interface ports, a non-ANSI in-body
// `If.Mp x;` declaration, struct bit and part selects, a nested same-name
// member and a module instantiated many times.  The Yosys-readable formal cone
// is formal_cone.sv, which t110_top instantiates.

interface t110_if;
    logic       req;
    logic       ack;
    logic [3:0] tag;
    modport Master (output req, input ack, input tag);
    modport Slave  (input req, output ack, output tag);
endinterface

typedef struct packed {
    logic       a;
    logic [3:0] b;
} t110_inner_t;

// The outer member `a` and the inner member `a` are spelled the same, so
// `word.a.a` must resolve to two different members.  The inner aggregate is
// anonymous on purpose: a named typedef used as a member type is a `NamedType`
// reference, which this task does not bind.
typedef struct packed {
    struct packed {
        logic       a;
        logic [3:0] b;
    } a;
    logic [7:0] user;
    logic       ok;
} t110_word_t;

// Struct bit select, struct part select and the nested same-name member
// word.a.a.
module t110_struct_user (
    input  logic [3:0] tag_i,
    input  logic       ok_i,
    output logic       bit_o,
    output logic [3:0] part_o
);
    t110_word_t  word;
    t110_inner_t inner;
    always_comb begin
        word      = '0;
        word.a.a  = ok_i;
        word.a.b  = tag_i;
        word.user = {tag_i, 4'h3};
        word.ok   = ok_i;
        inner.a   = ok_i;
        inner.b   = tag_i;
    end
    assign bit_o  = word.user[2] ^ word.a.a ^ word.ok ^ inner.a;
    assign part_o = word.user[7:4] ^ word.a.b ^ inner.b;
endmodule

// A modport-qualified ANSI interface port.  A member reference reached through
// a modport port resolves to ModportPortSymbol, which owns no rename record, so
// this port is declared and connected but not dereferenced here.
module t110_mp_ansi (
    t110_if.Master mp_port,
    output logic   out_bit
);
    assign out_bit = 1'b1;
endmodule

// A non-ANSI port list whose interface port is declared in the body as
// `If.Mp x;`.
module t110_mp_nonansi (mp2, out_bit);
    t110_if.Slave mp2;
    output logic  out_bit;
    assign out_bit = 1'b0;
endmodule

// A plain interface port with no modport qualifier.  Every interface member is
// both written and read through it.
module t110_if_user (
    t110_if            plain_port,
    input  logic       drive_i,
    input  logic [3:0] tag_i,
    output logic       out_bit
);
    assign plain_port.req = drive_i;
    assign plain_port.ack = drive_i;
    assign plain_port.tag = tag_i;
    assign out_bit = plain_port.req ^ plain_port.ack ^ (plain_port.tag != 4'h0);
endmodule

module t110_wild_child (
    input  logic x,
    input  logic y,
    output logic z
);
    assign z = x | y;
endmodule

// `.*` carries no label token, so it must produce no occurrence and no binding
// diagnostic.  An implicit connection is bound by name at elaboration and is
// not rewritten, so this pair is deliberately left outside the selected top's
// closure, where every port is preserved as `outside_top_closure`.
module t110_wild_parent (
    input  logic x,
    input  logic y,
    output logic wild_z
);
    logic z;
    t110_wild_child u_wild (.*);
    assign wild_z = z;
endmodule

module t110_top (
    input  logic       clk,
    input  logic       in_a,
    input  logic       in_b,
    input  logic [3:0] in_tag,
    output logic       out_y,
    output logic       out_sum,
    output logic       out_pos,
    output logic       out_bit,
    output logic [3:0] out_part,
    output logic       out_if
);
    t110_if bus0();
    t110_if bus1();
    t110_if bus_arr[1:0]();
    logic   ansi_bit;
    logic   nonansi_bit;
    logic   if_bit;

    t110_formal_top u_formal (
        .clk(clk),
        .in_a(in_a),
        .in_b(in_b),
        .out_y(out_y)
    );

    // A second reordered named instantiation and a positional instantiation of
    // the same reused modules, so this file carries both shapes too.
    t110_reorder u_reorder_again (
        .sum(out_sum),
        .c_third(in_a),
        .a_first(in_b),
        .b_second(in_a)
    );

    t110_leaf u_leaf_pos (in_a, in_b, out_pos);

    t110_struct_user u_struct (
        .tag_i(in_tag),
        .ok_i(in_a),
        .bit_o(out_bit),
        .part_o(out_part)
    );

    t110_if_user u_if_user (
        .plain_port(bus0),
        .drive_i(in_a),
        .tag_i(in_tag),
        .out_bit(if_bit)
    );

    t110_mp_ansi u_mp_ansi (
        .mp_port(bus1),
        .out_bit(ansi_bit)
    );

    t110_mp_nonansi u_mp_nonansi (
        .mp2(bus1),
        .out_bit(nonansi_bit)
    );

    assign out_if = if_bit ^ ansi_bit ^ nonansi_bit;
endmodule
