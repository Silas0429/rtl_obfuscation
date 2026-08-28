// T114 fixture: a gold implicit net whose spelling is renamed elsewhere too.
//
// `valid` stands for five distinct symbols here: a port of two different leaf
// modules, a declared local signal in two more, and -- inside
// `t114_collision_top` -- no declaration at all.  That last one is an implicit
// net the default nettype creates in the ORIGINAL source, the same shape T113
// traced to `valid` in `rtl/vector/vmu.sv`.
//
// Each of those symbols is renamed to a DIFFERENT new name, so a global
// `old name -> new name` dictionary can keep only one of them.  Translating the
// gold implicit net through such a dictionary yields the wrong gate spelling and
// reports a correct gate as `suspect`.
//
// Two properties are deliberate and are asserted by the test:
//
// * every module is instantiated from the top, so nothing here is dead source.
//   If `valid` were also written inside an unelaborated branch, T113's
//   `unelaborated_reference` rule would preserve every `valid` record, nothing
//   would be renamed, and the collision would never happen.
// * `t114_late_stage` is declared *after* the top module even though the top
//   instantiates it, so the last `valid` rename record in the mapping is not the
//   implicit net's own record.  That is what makes a global dictionary keep the
//   wrong value for `valid`.

module t114_sink_a (input logic valid, input logic payload, output logic out_a);
    assign out_a = valid & payload;
endmodule

module t114_sink_b (input logic valid, output logic out_b);
    assign out_b = ~valid;
endmodule

module t114_producer (input logic seed, output logic ready);
    logic valid;
    assign valid = seed;
    assign ready = valid;
endmodule

module t114_collision_top (
    input  logic src,
    output logic dst_a,
    output logic dst_b,
    output logic dst_c,
    output logic dst_d
);
    // `valid` is never declared in this module: the default nettype absorbs it
    // as an implicit wire, right here in the gold source.
    t114_producer   u_producer (.seed(src),    .ready(valid));
    t114_sink_a     u_sink_a   (.valid(valid), .payload(src), .out_a(dst_a));
    t114_sink_b     u_sink_b   (.valid(valid), .out_b(dst_b));
    t114_late_stage u_late     (.gate_in(src), .gate_out(dst_d));

    assign dst_c = valid;
endmodule

module t114_late_stage (input logic gate_in, output logic gate_out);
    logic valid;
    assign valid = ~gate_in;
    assign gate_out = valid;
endmodule
