module t104_conflict_a (
    output logic out_a
);
    logic conflict_body_signal;
    assign out_a = `T104_CONFLICT_BODY_REF;
endmodule

module t104_conflict_b (
    output logic out_b
);
    logic conflict_body_signal;
    assign out_b = `T104_CONFLICT_BODY_REF;
endmodule
