from pathlib import Path
import os
import shutil
from logging import getLogger
from fileformats.medimage_mrtrix3 import ImageIn, ImageFormat as Mif
import pydra.mark
from pydra.tasks.mrtrix3.auto import (
    mrconvert,   
)
from pydra.tasks.fsl.auto import EddyQuad

logger = getLogger(__name__)


def qc_wf():
    """Identify the strategy for DWI processing

    Parameters
    ----------

    Returns
    -------
    wf : pydra.Workflow
        Workflow object
    """

    wf = pydra.Workflow(
        name="qc_wf", input_spec=["input"]
    )

    wf.add(
        example_task(
            in_image=wf.lzin.input, name="example"
        )
    )

    wf.set_output(
        [
            ("example", wf.example.lzout.output),
        ],
    )

    return wf


@pydra.mark.task
@pydra.mark.annotate()
def example_task():
    eddyqc_mask = "eddy_mask.nii"
    eddyqc_fieldmap = fsl.find_image("field_map") if execute_topup else None
    eddyqc_slspec = "slspec.txt" if eddy_mporder else None


    # Check to see whether or not eddy has provided a rotated bvecs file;
    #   if it has, import this into the output image
    bvecs_path = "dwi_post_eddy.eddy_rotated_bvecs"
    if not os.path.isfile(bvecs_path):
        logger.warning(
            "eddy has not provided rotated bvecs file; using original gradient table. Recommend updating FSL eddy to version 5.0.9 or later."
        )
        bvecs_path = "bvecs"


    # Grab any relevant files that eddy has created, and copy them to the requested directory
    if eddyqc_path:
        if (
            app.FORCE_OVERWRITE
            and os.path.exists(eddyqc_path)
            and not os.path.isdir(eddyqc_path)
        ):
            run.function(os.remove, eddyqc_path)
        if not os.path.exists(eddyqc_path):
            run.function(os.makedirs, eddyqc_path)
        for filename in eddy_suppl_files:
            if os.path.exists(eddyqc_prefix + "." + filename):
                # If this is an image, and axis padding was applied, want to undo the padding
                if filename.endswith(".nii.gz") and dwi_post_eddy_crop:
                    wf.add(
                        mrconvert(
                            input=eddyqc_prefix + "." + filename,
                            output=os.path.join(eddyqc_path, filename),
                            coord=dwi_post_eddy_crop,
                            force=app.FORCE_OVERWRITE,
                            name="export_eddy_qc_image_%s" % filename,
                        )
                    )
                else:
                    run.function(
                        shutil.copy,
                        eddyqc_prefix + "." + filename,
                        os.path.join(eddyqc_path, filename),
                    )
        # Also grab any files generated by the eddy qc tool QUAD
        if os.path.isdir(eddyqc_prefix + ".qc"):
            if app.FORCE_OVERWRITE and os.path.exists(
                os.path.join(eddyqc_path, "quad")
            ):
                run.function(shutil.rmtree, os.path.join(eddyqc_path, "quad"))
            run.function(
                shutil.copytree,
                eddyqc_prefix + ".qc",
                os.path.join(eddyqc_path, "quad"),
            )
        # Also grab the brain mask that was provided to eddy if -eddyqc_all was specified
        if eddyqc_all:
            if dwi_post_eddy_crop:
                wf.add(
                    mrconvert(
                        input="eddy_mask.nii",
                        output=os.path.join(eddyqc_path, "eddy_mask.nii"),
                        coord=dwi_post_eddy_crop,
                        force=app.FORCE_OVERWRITE,
                        name="export_eddy_mask",
                    )
                )
            else:
                run.function(
                    shutil.copy,
                    "eddy_mask.nii",
                    os.path.join(eddyqc_path, "eddy_mask.nii"),
                )
            app.cleanup("eddy_mask.nii")

    keys_to_remove = [
        "MultibandAccelerationFactor",
        "SliceEncodingDirection",
        "SliceTiming",
    ]
    # These keys are still relevant for the output data if no EPI distortion correction was performed
    if execute_applytopup:
        keys_to_remove.extend(
            ["PhaseEncodingDirection", "TotalReadoutTime", "pe_scheme"]
        )

    eddyqc_kwargs = {}
    if os.path.isfile(eddyqc_prefix + ".eddy_residuals.nii.gz"):
        eddyqc_kwargs["bvecs"] = bvecs_path
    if execute_topup:
        eddyqc_kwargs["field"] = eddyqc_fieldmap
    if eddy_mporder:
        eddyqc_kwargs["slice_spec"] = eddyqc_slspec
    if app.VERBOSITY > 2:
        eddyqc_kwargs["verbose"] = True
    try:
        wf.add(
            EddyQuad(
                input=eddyqc_prefix,
                idx_file="eddy_indices.txt",
                param_file="eddy_config.txt",
                bvals="bvals",
                mask="eddyqc_mask",
                name="eddy_quad",
                **eddyqc_kwargs,
            )
        )
    except run.MRtrixCmdError as exception:
        with open(
            "eddy_quad_failure_output.txt", "wb"
        ) as eddy_quad_output_file:
            eddy_quad_output_file.write(
                str(exception).encode("utf-8", errors="replace")
            )
        logger.debug(str(exception))
        logger.warning(
            "Error running automated EddyQC tool 'eddy_quad'; QC data written to \""
            + eddyqc_path
            + '" will be files from "eddy" only'
        )
        # Delete the directory if the script only made it partway through
        try:
            shutil.rmtree(eddyqc_prefix + ".qc")
        except OSError:
            pass    