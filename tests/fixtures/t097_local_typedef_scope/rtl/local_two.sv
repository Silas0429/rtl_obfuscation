module t097_local_two;
    typedef logic [3:0] stsram_dat_bk1_t;

    function automatic stsram_dat_bk1_t local_value();
        local_value = '1;
    endfunction
endmodule
