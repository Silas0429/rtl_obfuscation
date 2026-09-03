function automatic logic [`T134_WIDTH-1:0] vendor_mix(
    input logic [`T134_WIDTH-1:0] value
);
    logic [`T134_WIDTH-1:0] scratch;
    begin
        scratch = value ^ `T134_WIDTH'h3;
        vendor_mix = scratch;
    end
endfunction
