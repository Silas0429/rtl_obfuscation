module t104_formal (
    input logic clk,
    input logic d,
    output logic q
);
    `T104_FORMAL_DECL(state);

    always_ff @(posedge clk) begin
        state <= `T104_FORMAL_REF(d);
    end

    assign q = `T104_FORMAL_REF(state);
endmodule
