module t104_unmappable (
    output logic out
);
    `T104_GEN_DECL(generated_, signal);
    assign out = generated_signal;
endmodule
