module t117_library_cell (
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic masked_value;

    assign masked_value = (in_a ^ in_b) ^ 1'b0;
    assign out_y = masked_value;
endmodule
