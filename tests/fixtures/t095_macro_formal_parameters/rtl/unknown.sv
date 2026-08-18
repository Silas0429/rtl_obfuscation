module t095_unknown(input logic in_a, output logic out_y);
    assign out_y = in_a & `__name;
endmodule
