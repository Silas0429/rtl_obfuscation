module t104_nonexact (
    output logic out
);
    logic paste_signal;
    assign `T104_PASTE(paste_, signal) = 1'b0;
    assign out = paste_signal;
endmodule
