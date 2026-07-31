module t070_invalid_nonkeyword;
    typedef logic [7:0] byte_t;
    byte_t value;

    always_comb begin
        value = 8'h3c;
    end
endmodule
