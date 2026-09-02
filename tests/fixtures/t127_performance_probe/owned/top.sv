module t127_probe_top (
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic probe_signal;

    assign probe_signal = in_a ^ in_b;
    assign out_y = probe_signal;
endmodule
