import time


def gen_transfer_packet(
    transfer_flow_id: str,
    source_account_iban: str,
    source_bic_code: str,
    holder: str,
    amount: float,
    recipient_account_iban: str,
    recipient_name: str,
    recipient_bic_code: str,
    motif: str,
    additional_motif: str,
    transfer_frequency_code: str | None = None,
) -> dict[str, str | int | float]:
    packet = {
        "transfer_flow_id": transfer_flow_id,
        "source_account_number": source_account_iban,
        "source_bic": source_bic_code,
        "source_name": holder,
        "date": int(time.time() * 1000),
        "amount": amount,
        "currency": "EUR",
        "recipient_account_number": recipient_account_iban,
        "recipient_name": recipient_name,
        "recipient_bic": recipient_bic_code,
        "remittance_information": motif,
        "additional_remittance_information": additional_motif,
    }

    if transfer_frequency_code is not None:
        packet["transfer_frequency_code"] = transfer_frequency_code

    return packet
