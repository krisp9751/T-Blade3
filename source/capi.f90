!
! C interface to T-Blade3 for the shared library (libTBlade3.so)
!
! Used by the Python package in python/tblade3 (ctypes). The derivative
! getters tb_get_xyz_ders_size and tb_get_xyz_ders are in file_operations.f90
!
!-------------------------------------------------------------------------------
module tb_capi
    use iso_c_binding,  only: c_char, c_int, c_null_char
    implicit none

    private
    public  :: tb_run

contains



    !
    ! Copy a null-terminated C string into a blank-padded Fortran string
    !
    !---------------------------------------------------------------------------
    subroutine c_to_f_string (cstr, fstr)

        character(kind = c_char),   intent(in)      :: cstr(*)
        character(*),               intent(out)     :: fstr

        ! Local variables
        integer                                     :: i

        fstr = ''
        do i = 1, len(fstr)
            if (cstr(i) == c_null_char) exit
            fstr(i:i) = cstr(i)
        end do

    end subroutine c_to_f_string
    !---------------------------------------------------------------------------



    !
    ! Run T-Blade3 in the current working directory
    !
    ! Input parameters: main_c  - main input file name (3dbgbinput.<row>.dat)
    !                   aux_c   - auxiliary input file name
    !                             (spancontrolinputs.<row>.dat)
    !                   arg2_c, arg3_c, arg4_c - the optional command line
    !                             arguments of the tblade3 executable
    !                             ('dev', 'xyzstreamlines', '2d', 'quiet')
    !                             or empty strings
    !
    ! Returns 0 when bgb3d_sub returns. A fatal error in T-Blade3 executes
    ! 'stop' and ends the calling process, so callers that need to survive
    ! one should load this library in a separate worker process
    !
    !---------------------------------------------------------------------------
    function tb_run (main_c, aux_c, arg2_c, arg3_c, arg4_c) result(ierr) bind(C, name = 'tb_run')

        character(kind = c_char),   intent(in)      :: main_c(*), aux_c(*)
        character(kind = c_char),   intent(in)      :: arg2_c(*), arg3_c(*), arg4_c(*)
        integer(c_int)                              :: ierr

        ! Local variables
        character(256)                              :: fname, aux
        character(32)                               :: arg2, arg3, arg4

        external                                    :: bgb3d_sub

        call c_to_f_string(main_c, fname)
        call c_to_f_string(aux_c,  aux)
        call c_to_f_string(arg2_c, arg2)
        call c_to_f_string(arg3_c, arg3)
        call c_to_f_string(arg4_c, arg4)

        call bgb3d_sub(fname, aux, arg2, arg3, arg4)
        ierr = 0

    end function tb_run
    !---------------------------------------------------------------------------

end module tb_capi
