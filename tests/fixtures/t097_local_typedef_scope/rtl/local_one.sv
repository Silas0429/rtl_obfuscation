module t097_local_one;
    typedef logic [3:0] stsram_dat_bk1_t;

    function automatic stsram_dat_bk1_t local_value();
        local_value = '0;
    endfunction
endmodule
